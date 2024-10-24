import glob
from setuptools import setup, find_packages

DATA_FILES = [
    ('share/jupyter/kernels/imatlab', [ 'kernel.json' ] + glob.glob('*.png')),
]

setup(
    name="imatlab",
    description="A Juyter kernel for MATLAB",
    long_description=open("README.rst", encoding="utf-8").read(),
    author="Antony Lee + Dan O'Shea",
    url="https://github.com/djoshea/imatlab",
    license="MIT",
    classifiers=[
        "Framework :: IPython",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Topic :: System :: Shells",
    ],
    packages=find_packages("lib"),
    package_dir={"": "lib"},
    package_data={"imatlab": ["res/imatlab_export_fig.m",
                              "res/is_dbstop_if_error.m",
                              "res/matlab.tpl"]},
    include_package_data=True,
    data_files=DATA_FILES,
    python_requires=">=3.5",
    setup_requires=["setuptools_scm"],
    use_scm_version=lambda: {  # xref __init__.py
        "version_scheme": "post-release",
        "local_scheme": "node-and-date",
        "write_to": "lib/imatlab/_version.py",
    },
    install_requires=[
        "ipykernel>=4.1",  # Current version of --user install.
        "nbconvert>=4.2",  # Exporter API.
        "plotly>=1.13.0",  # First version to test Py3.5.
        "widgetsnbextension>=1.0",  # Anything works.
        "matlabengine>=9.13",  
    ],
    entry_points = {
        "nbconvert.exporters": [
            "matlab = imatlab._exporter:MatlabExporter",
        ],
    },
)
