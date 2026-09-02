import subprocess
from pathlib import Path
from setuptools import setup, find_packages
from setuptools.command.build_py import build_py


class BuildWithC(build_py):
    def run(self):
        src_dir = Path(__file__).parent / "src"
        try:
            subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-o", "fastscan",
                             "fastscan.c"], cwd=src_dir, check=True)
        except Exception as e:  # pragma: no cover
            print(f"warning: could not compile fastscan C binary ({e}); "
                  f"gitweave will fall back to the pure-Python scanner.")
        super().run()


setup(
    name="gitweave",
    version="0.1.0",
    description="Organize a finished project into an honest, well-structured git commit history.",
    packages=find_packages(include=["gitweave", "gitweave.*"]),
    python_requires=">=3.10",
    entry_points={"console_scripts": ["gitweave=gitweave.cli:main"]},
    cmdclass={"build_py": BuildWithC},
    include_package_data=True,
)
