// SPDX-License-Identifier: GPL-2.0-only
/* nio AW882xx (chip ID 0x1852) bring-up component.
 * Register sequencing/calibration follow Motorola's GPL aw882xx driver.
 * Fixed -36 dB gain for bring-up; proprietary ADSP speaker protection is
 * not yet integrated. Do not expand gain before implementing that protection.
 */
#include <linux/delay.h>
#include <linux/firmware.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/unaligned.h>
#include <sound/pcm_params.h>
#include <sound/soc.h>

#define AW_ID 0x00
#define AW_STATUS 0x01
#define AW_CONTROL 0x04
#define AW_MUTE 0x05
#define AW_I2S 0x06
#define AW_VOLUME 0x0c
#define AW_CALIBRATION 0x56
#define AW_PLL 0x66
#define AW_EFUSE_V 0x78
#define AW_EFUSE_I 0x7a
#define AW_PWDN BIT(0)
#define AW_HMUTE BIT(4)
#define AW_FW "qcom/sm8250/nio/aw882xx_spk_reg.bin"

struct nio_aw {
 struct regmap *map;
 struct gpio_desc *reset;
 struct mutex lock;
};

static int nio_aw_off(struct nio_aw *aw)
{
 int mute = regmap_update_bits(aw->map, AW_MUTE, AW_HMUTE, AW_HMUTE);
 int power = regmap_update_bits(aw->map, AW_CONTROL, AW_PWDN, AW_PWDN);
 return mute ? mute : power;
}

static bool nio_aw_profile_register(unsigned int reg)
{
 return (reg >= 3 && reg <= 0xf) || reg == 0x20 || reg == 0x38 ||
  reg == 0x50 || (reg >= 0x52 && reg <= 0x56) || reg == 0x59 ||
  reg == 0x5a || (reg >= 0x60 && reg <= 0x6b) || reg == 0x70;
}

static int nio_aw_profile(struct device *dev, struct nio_aw *aw, unsigned int width)
{
 const struct firmware *fw;
 unsigned int i, reg, val, ef_i, ef_v;
 int ret, ical, voltage;
 ret = request_firmware(&fw, AW_FW, dev);
 if (ret)
  return ret;
 if (fw->size != 144) { ret = -EINVAL; goto release; }
 /* Validate the complete register list before doing any profile writes. */
 for (i = 0; i < fw->size; i += 4)
  if (!nio_aw_profile_register(get_unaligned_le16(fw->data + i))) {
   ret = -EINVAL; goto release;
  }
 ret = nio_aw_off(aw);
 if (ret)
  goto release;
 for (i = 0; i < fw->size; i += 4) {
  reg = get_unaligned_le16(fw->data + i);
  val = get_unaligned_le16(fw->data + i + 2);
  if (reg == AW_CONTROL) val |= AW_PWDN;
  if (reg == AW_MUTE) val |= AW_HMUTE;
  /* Vendor gain encoding: 6 dB steps in high nibble, 0.5 dB in low. */
  if (reg == AW_VOLUME) val = (val & 0xff) | 0x6000;
  ret = regmap_write(aw->map, reg, val);
  if (ret)
   goto off;
 }
 ret = regmap_read(aw->map, AW_EFUSE_I, &ef_i);
 if (ret) goto off;
 ret = regmap_read(aw->map, AW_EFUSE_V, &ef_v);
 if (ret) goto off;
 ical = 1000 + sign_extend32(ef_i & 0x3ff, 9);
 voltage = 1000 + sign_extend32(ef_v & 0x3ff, 9);
 if (ical <= 0 || voltage <= 0) { ret = -EINVAL; goto off; }
 ret = regmap_write(aw->map, AW_CALIBRATION, 8192 * ical / voltage);
 if (ret) goto off;
 ret = regmap_update_bits(aw->map, AW_PLL, BIT(14), BIT(14));
 if (ret) goto off;
 /* 32-bit: keep the stock profile framing (48 kHz, 32-bit, 64fs, left, V/I TX on SD0 for the
  * ADSP speaker protection). 16-bit stereo: the original unprotected bring-up route. */
 if (width == 16)
  ret = regmap_update_bits(aw->map, AW_I2S, 0xcf, 8);
off:
 if (ret) nio_aw_off(aw);
release:
 release_firmware(fw);
 return ret;
}

static int nio_aw_hw_params(struct snd_pcm_substream *stream,
 struct snd_pcm_hw_params *params, struct snd_soc_dai *dai)
{
 struct nio_aw *aw = snd_soc_component_get_drvdata(dai->component);
 int ret;
 if (params_rate(params) != 48000 ||
     !((params_width(params) == 16 && params_channels(params) == 2) ||
       (params_physical_width(params) == 32 && params_channels(params) == 1)))
  return -EINVAL;
 mutex_lock(&aw->lock);
 ret = nio_aw_profile(dai->dev, aw, params_physical_width(params));
 mutex_unlock(&aw->lock);
 return ret;
}

static int nio_aw_set_fmt(struct snd_soc_dai *dai, unsigned int fmt)
{
 if ((fmt & SND_SOC_DAIFMT_FORMAT_MASK) != SND_SOC_DAIFMT_I2S ||
     (fmt & SND_SOC_DAIFMT_CLOCK_PROVIDER_MASK) != SND_SOC_DAIFMT_BC_FC ||
     (fmt & SND_SOC_DAIFMT_INV_MASK) != SND_SOC_DAIFMT_NB_NF)
  return -EINVAL;
 return 0;
}

static int nio_aw_mute(struct snd_soc_dai *dai, int mute, int direction)
{
 struct nio_aw *aw = snd_soc_component_get_drvdata(dai->component);
 unsigned int status;
 int ret;
 mutex_lock(&aw->lock);
 if (mute) { ret = nio_aw_off(aw); goto out; }
 ret = regmap_update_bits(aw->map, AW_CONTROL, AW_PWDN, 0);
 if (ret) goto fail;
 /* PLL + clock present, no undervoltage, overical or overtemperature. */
 ret = regmap_read_poll_timeout(aw->map, AW_STATUS, status,
  (status & 0x401b) == 0x11, 2000, 20000);
 if (ret) goto fail;
 ret = regmap_update_bits(aw->map, AW_MUTE, AW_HMUTE, 0);
 if (!ret) goto out;
fail:
 nio_aw_off(aw);
out:
 mutex_unlock(&aw->lock);
 return ret;
}

static const struct snd_soc_dai_ops nio_aw_ops = {
 .set_fmt = nio_aw_set_fmt,
 .hw_params = nio_aw_hw_params,
 .mute_stream = nio_aw_mute,
 .no_capture_mute = 1,
};
static struct snd_soc_dai_driver nio_aw_dai = {
 .name = "aw882xx-nio-aif",
 .playback = {
  .stream_name = "Speaker Playback",
  .channels_min = 1, .channels_max = 2,
  .rates = SNDRV_PCM_RATE_48000,
  .formats = SNDRV_PCM_FMTBIT_S16_LE | SNDRV_PCM_FMTBIT_S24_LE | SNDRV_PCM_FMTBIT_S32_LE,
 },
 .ops = &nio_aw_ops,
};
static const struct snd_soc_dapm_widget nio_aw_widgets[] = {
 SND_SOC_DAPM_AIF_IN("AIF RX", "Speaker Playback", 0, SND_SOC_NOPM, 0, 0),
 SND_SOC_DAPM_OUTPUT("Speaker Output"),
};
static const struct snd_soc_dapm_route nio_aw_routes[] = {
 { "Speaker Output", NULL, "AIF RX" },
};
static const struct snd_soc_component_driver nio_aw_component = {
 .dapm_widgets = nio_aw_widgets, .num_dapm_widgets = ARRAY_SIZE(nio_aw_widgets),
 .dapm_routes = nio_aw_routes, .num_dapm_routes = ARRAY_SIZE(nio_aw_routes),
};
static const struct regmap_config nio_aw_regmap = {
 .reg_bits = 8, .val_bits = 16, .max_register = 0x7c,
 .val_format_endian = REGMAP_ENDIAN_BIG,
 .cache_type = REGCACHE_NONE,
};
static void nio_aw_cleanup(void *data)
{
 struct nio_aw *aw = data;
 nio_aw_off(aw);
 gpiod_set_value_cansleep(aw->reset, 1);
}
static int nio_aw_probe(struct i2c_client *client)
{
 struct nio_aw *aw;
 unsigned int id;
 int ret;
 aw = devm_kzalloc(&client->dev, sizeof(*aw), GFP_KERNEL);
 if (!aw) return -ENOMEM;
 mutex_init(&aw->lock);
 i2c_set_clientdata(client, aw);
 aw->map = devm_regmap_init_i2c(client, &nio_aw_regmap);
 if (IS_ERR(aw->map)) return PTR_ERR(aw->map);
 aw->reset = devm_gpiod_get(&client->dev, "reset", GPIOD_OUT_HIGH);
 if (IS_ERR(aw->reset)) return dev_err_probe(&client->dev, PTR_ERR(aw->reset), "reset GPIO unavailable\n");
 usleep_range(1000, 2000);
 gpiod_set_value_cansleep(aw->reset, 0);
 usleep_range(1000, 2000);
 ret = devm_add_action_or_reset(&client->dev, nio_aw_cleanup, aw);
 if (ret) return ret;
 ret = regmap_read(aw->map, AW_ID, &id);
 if (ret) return dev_err_probe(&client->dev, ret, "chip ID read failed\n");
 if (id != 0x1852) return dev_err_probe(&client->dev, -ENODEV, "unsupported chip ID %#x\n", id);
 ret = nio_aw_profile(&client->dev, aw, 32);
 if (ret) return dev_err_probe(&client->dev, ret, "muted profile init failed\n");
 dev_info(&client->dev, "AW882xx ID %#x initialized muted, powered down, gain -36 dB\n", id);
 return devm_snd_soc_register_component(&client->dev, &nio_aw_component, &nio_aw_dai, 1);
}
static const struct of_device_id nio_aw_of[] = {
 { .compatible = "mothership,nio-aw882xx" }, { }
};
MODULE_DEVICE_TABLE(of, nio_aw_of);
static struct i2c_driver nio_aw_driver = {
 .driver = { .name = "aw882xx-nio", .of_match_table = nio_aw_of },
 .probe = nio_aw_probe,
};
module_i2c_driver(nio_aw_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Motorola nio AW882xx 0x1852 speaker bring-up component");
MODULE_FIRMWARE(AW_FW);
