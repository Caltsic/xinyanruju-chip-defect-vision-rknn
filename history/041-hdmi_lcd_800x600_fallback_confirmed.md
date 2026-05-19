# HDMI LCD 800x600 Fallback Confirmed

Updated: 2026-05-06

## Symptom

The TaishanPi 3M was connected to a 7-inch IPS HDMI LCD. Higher or panel-specific modes caused bad physical output on the LCD, including blue-screen behavior.

## Board Access

ADB device:

```text
2e2609c37dc21c0a
```

Board OS:

```text
Linux TaishanPi-3M 6.1.99 aarch64
Debian GNU/Linux 12 (bookworm)
```

## Modes Checked

`xrandr` advertised these lower HDMI modes:

```text
1024x600 @ 60.05
800x600  @ 60.32
720x576  @ 50.00
720x480  @ 60.00 / 59.94
640x480  @ 60.00 / 59.94
```

Although `1024x600` was advertised as the EDID preferred mode, the user reported that the current TaishanPi/LCD path did not support it acceptably in practice.

## Applied Fix

The board was switched to the standard fallback mode `800x600@60.32`:

```bash
DISPLAY=:0 XAUTHORITY=/home/lckfb/.Xauthority \
xrandr --output HDMI-1 \
  --set output_hdmi_dvi force_dvi \
  --set color_format rgb \
  --set color_depth 24bit \
  --mode 800x600 \
  --rate 60.32
```

Persistent XFCE profile:

```text
/Default/HDMI-1/Resolution    800x600
/Default/HDMI-1/RefreshRate   60.317257
/Fallback/HDMI-1/Resolution   800x600
/Fallback/HDMI-1/RefreshRate  60.317257
```

Autostart guard updated:

```text
/usr/local/bin/chipcheck-hdmi-mode
/home/lckfb/.config/autostart/chipcheck-hdmi-mode.desktop
```

The guard reapplies:

```text
800x600@60.32
output_hdmi_dvi: force_dvi
color_format: rgb
color_depth: 24bit
```

## Verification

Software-side state:

```text
Screen 0: current 800 x 600
HDMI-1 connected 800x600+0+0
output_hdmi_dvi: force_dvi
color_format: rgb
color_depth: 24bit
link-status: Good
xdpyinfo dimensions: 800x600 pixels
```

Physical LCD result:

```text
User confirmed the current 800x600 display is good.
```

## Follow-Up

Keep `800x600@60.32 RGB force_dvi` as the default for this LCD/controller combination.

If a future screen or controller behaves differently, the next lower fallback is `640x480@60`. Higher modes such as `1024x600`, `1280x720`, and `1920x1080` should only be used after direct physical-screen confirmation.
