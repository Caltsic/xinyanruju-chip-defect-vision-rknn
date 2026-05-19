# TaishanPi Qt Board GUI 2026-05-07

## Goal

Build and deploy a board-local Qt GUI for TaishanPi 3M so the HDMI screen can run the simplified ChipCheck segmentation workflow without the OpenCV UI or PC ADB frame transport.

## Scope

- Keep the PC PyQt GUI behavior intact.
- Add a Linux/board launch path using the existing `local` camera backend.
- Fit the board's confirmed `800x600` HDMI LCD mode.
- Install board dependencies with Debian packages where possible.
- Treat the provided proxy subscription as operational secret material; do not commit it or record it in documentation.

## Phases

1. [complete] Inspect existing board GUI and TaishanPi environment.
2. [complete] Add PyQt CLI/board UI support and board launcher files.
3. [complete] Install/verify PyQt runtime on TaishanPi.
4. [complete] Sync code and launchers to `/userdata/chipcheck_vision`.
5. [complete] Run compile, import, and short local-backend smoke tests.
6. [complete] Archive the final command and board state.
7. [complete] Add chip-only bbox overlay to the live display.
8. [complete] Convert the board Qt toolbar to a collapsed floating overlay.

## Findings

- Board is online over ADB as `2e2609c37dc21c0a`.
- Board OS is Debian 12 bookworm on `Linux TaishanPi-3M 6.1.99`.
- Current Miniforge Python is `3.13.12`, has `cv2`, but lacks `PyQt5`.
- System Python is `3.11.2`, currently lacks `PyQt5`, `cv2`, and `numpy`.
- Apt sees `python3-pyqt5`, `python3-opencv`, and `python3-numpy` from Debian bookworm arm64.
- Board can ping `deb.debian.org`; proxy may not be needed for apt.
- The board display is confirmed stable at `800x600@60.32`.
- Qt launcher short-run through X11 succeeds after forcing non-GL/software rendering settings.
- Local backend preflight is `camera=True`, `stream=True`, `spidev=True`.
- A 3-frame local backend read succeeded with 1280x720 frames.
- Chip-only bbox overlay is enabled for Qt/OpenCV GUI rendering and the two-stage CLI live view; defect classes stay mask/contour-only.
- Launcher duplicate-instance detection must avoid matching its own `pgrep` invocation.
- Board UI preview now occupies the full 800x600 surface; the floating toolbar overlays the right side only when expanded.

## Decisions

- Prefer system Python plus Debian packages for Qt runtime.
- Add `--board-ui`, `--backend local`, and explicit window size options to the PyQt entrypoint.
- Add a separate Qt launcher instead of deleting the existing OpenCV fallback launcher.
- Do not install the proxy because Debian apt worked directly; keep the subscription out of repo files and logs.
- Draw the `chip` bbox as a lightweight ROI reference in segmentation display mode, but do not reintroduce defect bbox toggles or defect bbox overlays.
- Use a `[p]ython3` `pgrep` pattern in the launcher guard to prevent false `already running` exits.
- Keep the PC PyQt side panel unchanged; apply the collapsed floating toolbar only to `--board-ui`.
