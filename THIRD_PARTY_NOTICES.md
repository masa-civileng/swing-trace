# Third-party dependencies

This source archive does not bundle installed Python packages, FFmpeg binaries, or fonts. Installation downloads dependencies separately. Retain and follow the licenses included with each installed distribution.

- FastAPI / Uvicorn / Starlette / HTTPX / pytest: see the licenses shipped with their Python distributions.
- Pillow: see its HPND license and bundled component notices.
- imageio-ffmpeg: see its BSD license; the bundled FFmpeg executable has its own license and build options.
- FFmpeg: LGPL or GPL conditions depend on the build and enabled codecs; libx264 builds generally have GPL conditions. The Docker image installs the distribution's FFmpeg package.
- Noto CJK fonts: SIL Open Font License; the Docker image installs the distribution font package.
- Windows Meiryo is used only from the user's existing Windows installation for local rendering and is not redistributed.

If distributing a built container or executable rather than this source archive, include the relevant dependency notices and meet the obligations of that distribution, including FFmpeg's applicable license.
