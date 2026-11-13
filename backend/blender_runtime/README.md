# Local Blender layout tool

`wrapper.py` is vendored unchanged from IRCSS/comfyUI-blender-wrapper (MIT;
see LICENSE), retrieved 2026-10-10. This project invokes its headless protocol
directly; it does not require installing a ComfyUI node or restarting ComfyUI.

`main.py` is the trusted layout template. Text AI returns validated stage3d
JSON only. Each render builds an isolated .blend containing this Main text,
passes a JSON config to the wrapper, and retains PNG and editable .blend.

Default Blender: D:\2video\blender-5.4.0\blender.exe.
Override with DIRECTOR_BLENDER_EXE. Layout uses metres, Y up, +Z facing.
Render is a static sampled time; animation export remains the browser previs.
Supported proxies: characters, boxes, spheres, walls, tables, chairs, doors.
Generic poses approximate blocking, not fine facial or hand animation.
