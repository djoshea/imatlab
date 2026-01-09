# try:
#     import setuptools_scm
#     __version__ = setuptools_scm.get_version(  # xref setup.py
#         root="../..", relative_to=__file__,
#         version_scheme="post-release", local_scheme="node-and-date")
# except (ImportError, LookupError):
#     try:
#         from ._version import version as __version__
#     except ImportError:
#         pass

try:
    import importlib.metadata as _importlib_metadata
except ImportError:
    import importlib_metadata as _importlib_metadata
try:
    __version__ = _importlib_metadata.version("imatlab")
except _importlib_metadata.PackageNotFoundError:
    pass