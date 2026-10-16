# PlatformIO pre-build script (platformio.ini: extra_scripts): passes the git version
# of the source tree to the firmware as PIDG_FIRMWARE_VERSION, which ID? reports.
#
# The version is `git describe --always --dirty`: the commit (or tag) the image was
# built from, with "-dirty" if the tree had uncommitted changes. Unlike a build date
# it is the same for every build of the same source, so the build stays reproducible.
# Without git, or outside a git checkout, it is "unknown" (src/main.cpp's default).
import subprocess

Import("env")  # noqa: F821 -- provided by PlatformIO's SCons environment


def git_version(project_dir):
    try:
        out = subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    version = out.stdout.strip()
    return version if out.returncode == 0 and version else None


version = git_version(env.subst("$PROJECT_DIR"))  # noqa: F821
if version:
    env.Append(CPPDEFINES=[("PIDG_FIRMWARE_VERSION", env.StringifyMacro(version))])  # noqa: F821
print("PiDG firmware version: %s" % (version or "unknown"))
