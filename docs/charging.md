# Charging and battery

> Bring-up log moved from the old PORT-NOTES diary (2026-10-08..12); dated entries are as written then.
> Paths were updated to the current repo layout.

## Charging (2026-10-12)
- Before: no power_supply at all and SMB5 CHARGING_ENABLE_CMD = 0 (status DISABLE_CHARGE): the phone ran from
  USB without ever charging. FG gen4 kept running with the stock-loaded profile (MSOC 0x4009 = 82%).
- New driver drivers/power/supply/qcom_pm8150b_charger.c (patch 0010, CONFIG_CHARGER_QCOM_PM8150B=m), DT node
  pmic@2/charger@1000 (compatible qcom,pm8150b-charger-fg) in nio-el2-display.dts, FIT nio-el2-charge.itb:
  * "pm8150b-charger" (USB): APSD (SDP 500 / CDP 1500 / DCP 1500) or Type-C Rp (1.5/3 A), capped at 3 A, HC
    mode + AICL with periodic rerun; FCC (50 mA/step) and FV (3.6 V + 10 mV/step) programmed by policy.
  * "battery": MSOC, VBATT/IBATT (shadowed regs, 122.07 uV / 488.281 uA per LSB; FG positive = discharge,
    exported negated), temperature = FG SRAM word 328 via DMA (partition map 0x4420.. step 2 B/word, request
    MEM_ARB + MEM_ACCESS, poll MEM_IF_INT_RT_STS bit3), learned capacity word 285.
  * policy every 10 s + on USBIN plugin/APSD/ICL and CHGR state IRQs: stock mmi-temp-zones (cold <0 C stop,
    0-10 2.5 A/0.97 A above 4.2 V, 10-15 2.5 A, 15-45 4 A/3.6 A, 45-60 2.5 A held at 4.2 V, >=60 stop,
    2 C hysteresis); FV 4.45 V; iterm 150 mA; charge_control_{start,end}_threshold + charge_behaviour
    inhibit-charge. PMIC JEITA + safety timer stay enabled. Unknown temperature -> 1 A.
  * verified: charging on PC SDP (500 mA ICL), current sign (screen off +252 mA, load -1.47 A), temp 36 C,
    charge limit 80% stops at 82%, inhibit/auto.
- Userspace: mship-admin battery-*, /etc/mothership/battery.json applied at boot by mothershipd (mship-admin battery-apply); shell
  Battery page + home indicator; mship-sleepd powers off at <=2% discharging and does not suspend while
  charging towards a charge limit.
- Not done: USB PD / QC (would need TCPM: qcom_pmic_tcpm + pdphy instead of our cc-orientation driver), USB3
  SDP 900 mA, FG profile loading (relies on the stock profile already in FG SRAM), wireless/DC-in.
