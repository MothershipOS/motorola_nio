// mothershipOS bring-up: synthetic touchscreen (uinput) that taps or swipes, to test touch paths
// without a finger. usage: touchinject tap X Y | swipe X0 Y0 X1 Y1 [ms] | key CODE   (panel coords 1080x2520)
#include <fcntl.h>
#include <linux/uinput.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static int fd;
static void ev(int type, int code, int val)
{
	struct input_event e = { .type = type, .code = code, .value = val };
	if (write(fd, &e, sizeof(e)) != sizeof(e))
		perror("write");
}
static void syn(void) { ev(EV_SYN, SYN_REPORT, 0); }
static void msleep(int ms) { struct timespec t = { ms / 1000, (ms % 1000) * 1000000L }; nanosleep(&t, 0); }
static void absinfo(int code, int max)
{
	struct uinput_abs_setup a = { .code = code, .absinfo = { .maximum = max } };
	ioctl(fd, UI_ABS_SETUP, &a);
	ioctl(fd, UI_SET_ABSBIT, code);
}
static void down(int x, int y) { ev(EV_ABS, ABS_MT_SLOT, 0); ev(EV_ABS, ABS_MT_TRACKING_ID, 1);
	ev(EV_ABS, ABS_MT_POSITION_X, x); ev(EV_ABS, ABS_MT_POSITION_Y, y); ev(EV_KEY, BTN_TOUCH, 1);
	ev(EV_ABS, ABS_X, x); ev(EV_ABS, ABS_Y, y); syn(); }
static void move(int x, int y) { ev(EV_ABS, ABS_MT_POSITION_X, x); ev(EV_ABS, ABS_MT_POSITION_Y, y);
	ev(EV_ABS, ABS_X, x); ev(EV_ABS, ABS_Y, y); syn(); }
static void up(void) { ev(EV_ABS, ABS_MT_TRACKING_ID, -1); ev(EV_KEY, BTN_TOUCH, 0); syn(); }

int main(int argc, char **argv)
{
	struct uinput_setup us = { .id = { .bustype = BUS_VIRTUAL, .vendor = 0x1d6b, .product = 0x7001 } };

	if (argc < 3 || (argc < 4 && strcmp(argv[1], "key"))) { fprintf(stderr, "usage: %s tap X Y | swipe X0 Y0 X1 Y1 [ms]\n", argv[0]); return 2; }
	fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
	if (fd < 0) { perror("/dev/uinput"); return 1; }
	ioctl(fd, UI_SET_EVBIT, EV_KEY); ioctl(fd, UI_SET_KEYBIT, BTN_TOUCH);
	if (!strcmp(argv[1], "key"))	/* separate keyboard-like device for button tests */
		ioctl(fd, UI_SET_KEYBIT, atoi(argv[2]));
	ioctl(fd, UI_SET_EVBIT, EV_ABS); ioctl(fd, UI_SET_PROPBIT, INPUT_PROP_DIRECT);
	absinfo(ABS_X, 1079); absinfo(ABS_Y, 2519);
	absinfo(ABS_MT_SLOT, 9); absinfo(ABS_MT_TRACKING_ID, 65535);
	absinfo(ABS_MT_POSITION_X, 1079); absinfo(ABS_MT_POSITION_Y, 2519);
	strcpy(us.name, "mship-touchinject");
	ioctl(fd, UI_DEV_SETUP, &us); ioctl(fd, UI_DEV_CREATE);
	msleep(1500);				/* let the compositor pick the device up */
	if (!strcmp(argv[1], "key")) {
		ev(EV_KEY, atoi(argv[2]), 1); syn(); msleep(60); ev(EV_KEY, atoi(argv[2]), 0); syn();
	} else if (!strcmp(argv[1], "tap")) {
		down(atoi(argv[2]), atoi(argv[3])); msleep(80); up();
	} else if (!strcmp(argv[1], "swipe") && argc >= 6) {
		int x0 = atoi(argv[2]), y0 = atoi(argv[3]), x1 = atoi(argv[4]), y1 = atoi(argv[5]);
		int ms = argc > 6 ? atoi(argv[6]) : 400, n = ms / 16 ? ms / 16 : 1;
		down(x0, y0);
		for (int i = 1; i <= n; i++) { msleep(16); move(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n); }
		up();
	}
	msleep(300);
	ioctl(fd, UI_DEV_DESTROY);
	return 0;
}
