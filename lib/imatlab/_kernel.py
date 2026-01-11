import base64
from contextlib import ExitStack
from io import StringIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch
import uuid
import warnings
import weakref
from xml.etree import ElementTree as ET

import ipykernel.kernelspec
from ipykernel.kernelbase import Kernel
import IPython
from IPython.core.interactiveshell import InteractiveShell

# Work around LD_PRELOAD tricks played by MATLAB by looking for a working
# import order.
if subprocess.call(
        [sys.executable, "-c", "import plotly, matlab.engine"],
        stderr=subprocess.DEVNULL) == 0:
    import plotly
    import matlab.engine
    from matlab.engine import EngineError, MatlabExecutionError
elif subprocess.call(
        [sys.executable, "-c", "import matlab.engine, plotly"],
        stderr=subprocess.DEVNULL) == 0:
    import matlab.engine
    from matlab.engine import EngineError, MatlabExecutionError
    import plotly
else:
    import matlab.engine
    from matlab.engine import EngineError, MatlabExecutionError
    plotly = None
    warnings.warn(
        "Failed to import both matlab.engine and plotly in the same process; "
        "plotly output is unavailable.")

from . import _redirection, __version__

# debugpy.listen(5678) # ensure that this port is the same as the one in your launch.json
# print("Waiting for debugger attach")
# debugpy.wait_for_client()
# debugpy.breakpoint()
# print('break on this line')

# Support `python -mimatlab install`.
ipykernel.kernelspec.KERNEL_NAME = "imatlab"
# Changed in newer version
# ipykernel.kernelspec.get_kernel_dict = lambda extra_arguments=None: {
#     "argv": [sys.executable,
#              "-m", __name__.split(".")[0],
#              "-f", "{connection_file}"],
#     "display_name": "MATLAB",
#     "language": "matlab",
# }
ipykernel.kernelspec.get_kernel_dict = lambda extra_arguments=None, python_arguments=None: {
    "argv": [sys.executable,
             "-Xfrozen_modules=off",
             "-m", __name__.split(".")[0],
             "-f", "{connection_file}"],
    "display_name": "MATLAB",
    "language": "matlab",
}

class MatlabHistory:
    # The MATLAB GUI relies on `History.xml` (which uses a ridiculously fragile
    # parser); the command line (-nodesktop) interface on `history.m`.  We read
    # the former but update both files.

    def __init__(self, prefdir):
        self._prefdir = prefdir
        self._as_list = []
        try:
            self._et = ET.parse(str(prefdir / "History.xml"))
            root = self._et.getroot()
            self._session = ET.SubElement(root, "session")
            self._session.text = "\n"
            self._session.tail = "\n"
            command = ET.SubElement(
                self._session, "command",
                {"time_stamp": format(int(time.time() * 1000), "x")})
            command.text = time.strftime("%%-- %m/%d/%Y %I:%M:%S %p --%%")
            command.tail = "\n"
            self._as_list.extend(
                (session_number, line_number, elem.text)
                for session_number, session in enumerate(list(root), 1)
                for line_number, elem in enumerate(session, 1))
        except FileNotFoundError:
            self._et = self._session = None

    def append(self, text, elapsed, success):
        if self._et is not None:
            command = ET.SubElement(
                self._session, "command",
                {"execution_time": str(int(elapsed * 1000)),
                **({} if success else {"error": "true"})})
            command.text = text
            command.tail = "\n"
            last_session, last_line, _ = self._as_list[-1]
            self._as_list.append((last_session, last_line + 1, text))
            with (self._prefdir / "History.xml").open("r+b") as file:
                next(file)  # Skip the XML declaration, which is fragile.
                file.truncate()
                self._et.write(file, "utf-8", xml_declaration=False)
        with (self._prefdir / "history.m").open("a") as file:
            file.write(text)
            file.write("\n")

    @property
    def as_list(self):
        return self._as_list


class MatlabKernel(Kernel):
    implementation = banner = "MATLAB Kernel"
    implementation_version = __version__
    language = "matlab"

    def _call(self, *args, **kwargs):
        """Call a MATLAB function through `builtin` to bypass overloading.
        """
        return self._engine.builtin(*args, **kwargs)

    def _eval(self, *args, **kwargs):
        return self._engine.builtin("eval", *args, **kwargs)

    def _call_async(self, *args, **kwargs):
        """Call a MATLAB function asynchronously, returning a Future.
        """
        kwargs['background'] = True
        return self._engine.builtin(*args, **kwargs)

    def _execute_with_debug_detection(self, code, nargout=0):
        """Execute code asynchronously with detection for when debugging completes.

        This handles the case where MATLAB enters the debugger during execution.
        When the user interacts with the debugger via MATLAB Desktop and then
        exits (e.g., via dbquit), this method detects that MATLAB is responsive
        again and returns, even if the original Future doesn't properly complete.

        Returns True if execution completed normally, False if there was an error.
        Raises exceptions for engine errors.
        """
        # Execute the code asynchronously
        future = self._call_async("eval", code, nargout=nargout)

        poll_interval = 0.1  # seconds between done() checks
        probe_interval = 2.0  # seconds between probe attempts
        last_probe_time = time.time()

        while True:
            # Check if the main execution completed
            if future.done():
                # Get result to propagate any exceptions
                future.result()
                return True

            time.sleep(poll_interval)

            # Periodically try to probe MATLAB to see if it's responsive
            # This handles the case where the user exits the debugger but
            # the Future doesn't properly complete
            current_time = time.time()
            if current_time - last_probe_time >= probe_interval:
                last_probe_time = current_time
                try:
                    # Try a quick background probe with a short timeout
                    # If MATLAB is in debug mode, this will block/timeout
                    # If MATLAB is responsive, this will complete quickly
                    probe_future = self._engine.eval("1", background=True)
                    probe_future.result(timeout=0.5)

                    # If we get here, MATLAB is responsive
                    # Check again if main future is done (race condition)
                    if future.done():
                        future.result()
                        return True

                    # MATLAB is responsive but main future isn't done
                    # This likely means the future is "stuck" after debugging
                    # Check if we're actually still in debug mode
                    try:
                        in_debug = self._engine.is_in_debug_mode()
                        if not in_debug:
                            # Not in debug mode, MATLAB responsive, but future not done
                            # The execution likely completed but future didn't update
                            self.log.warning(
                                "MATLAB is responsive and not in debug mode, "
                                "but execution future not marked done. "
                                "Assuming execution completed.")
                            try:
                                future.cancel()
                            except:
                                pass
                            return True
                    except:
                        # Couldn't check debug mode, assume we should wait
                        pass

                except Exception:
                    # Probe timed out or failed - MATLAB is busy (likely debugging)
                    # Continue waiting
                    pass

    @property
    def language_info(self):
        # We also hook this property to `cd` into the current directory if
        # required.
        # if self._call("getenv", "IMATLAB_CD"):
        #     self._call("cd", str(Path().resolve()))
        return {
            "name": "matlab",
            "version": "R2024b",
            # "version": self._call("version"),
            "mimetype": "text/x-matlab",
            "file_extension": ".m",
            "pygments_lexer": "matlab",
            "codemirror_mode": "octave",
            "nbconvert_exporter": "imatlab._exporter.MatlabExporter",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._silent = False

        # console, qtconsole uses `kernel-$pid`, notebook uses `kernel-$uuid`.
        self._has_console_frontend = bool(re.match(
            r"\Akernel-\d+\Z",
            Path(self.config["IPKernelApp"]["connection_file"]).stem))

        if os.name == "posix":
            with ExitStack() as stack:
                for name in ["stdout", "stderr"]:
                    stream = getattr(sys, "__{}__".format(name))
                    def callback(data, *, _name=name, _stream=stream):
                        if not self._silent:
                            self._send_stream(
                                _name, data.decode(_stream.encoding))
                    stack.enter_context(
                        _redirection.redirect(stream.fileno(), callback))
                weakref.finalize(self, stack.pop_all().close)

        self._dead_engines = []
        engine_name = os.environ.get("IMATLAB_CONNECT")
        print("Launching MATLAB")
        self.log.error("Launching MATLAB engine")
        if engine_name:
            if re.match(r"\A(?a)[a-zA-Z]\w*\Z", engine_name):
                self._engine = matlab.engine.connect_matlab(engine_name)
            else:
                self._engine = matlab.engine.connect_matlab()
        else:
            self._engine = matlab.engine.start_matlab()
        # self._history = MatlabHistory(Path(self._call("prefdir")))

        self.log.error("Adding resources to MATLAB path")
        resources_path = str(Path(sys.modules[__name__.split(".")[0]].__file__).
            with_name("res"))
        self._engine.addpath(resources_path,"-end")
        self.log.error("DONE Adding resources to MATLAB path")

        # set env var to let Matlab code know its in Jupyter kernel
        self._engine.setenv("JUPYTER_KERNEL", "imatlab", nargout=0)

        try_startup_code = (
            "try, startupJupyter, catch, end"
        )
        self.log.error("Running startupJupyter")
        self._call("eval", try_startup_code, nargout=0)
        self.log.error("DONE Running startupJupyter")

        self._do_execute_first = True

    def _send_stream(self, stream, text):
        self.send_response(self.iopub_socket,
                           "stream",
                           {"name": stream, "text": text})

    def _send_display_data(self, data, metadata):
        # ZMQDisplayPublisher normally handles the conversion of `None`
        # metadata to {}.
        self.send_response(self.iopub_socket,
                           "display_data",
                           {"data": data, "metadata": metadata or {}})

    def do_execute(
            self, code, silent, store_history=True,
            # Neither of these is supported.
            user_expressions=None, allow_stdin=False):

        if self._do_execute_first:
            future = self._engine.is_dbstop_if_error(background=True)
            time.sleep(1)
            future.cancel()

            self._do_execute_first = False


        # self.log.error("Begin do_execute command")

        status = "ok"
        # if silent:
        #     self._silent = True
        start = time.perf_counter()

        # The debugger may have been set e.g. in startup.m (or later), but it
        # interacts poorly with the engine.
        #self._call("dbclear", "all", nargout=0)

        # here we set and then clear an environment variable that indicates the
        # code is being run within Jupyter (and not the desktop)
        code_pre = "imatlab_pre_execute();"
        code_post = "imatlab_post_execute();"

        # Don't include the "Error using eval" before each output.
        # This does not distinguish between `x` and `eval('x')` (with `x`
        # undefined), so a better solution would be preferred.
        try_code = (
            "{code_pre} "
            "try, {code}\n" # Newline needed as code may end with a comment.
            r"catch {me}; fprintf('%s\n', {me}.getReport); clear {me}; {code_post} end;"
            " {code_post}"
            .format(code=code, code_pre=code_pre, code_post=code_post,
                    me="ME{}".format(str(uuid.uuid4()).replace("-", ""))))

        no_try_code = (
            "{code_pre} {code}\n {code_post}"
            .format(code=code, code_pre=code_pre, code_post=code_post))

        if os.name == "posix":
            try:
                # call wrapped in try / catch if we're not debugging
                isdbg = self._engine.is_dbstop_if_error()
            except (SyntaxError, MatlabExecutionError, KeyboardInterrupt):
                isdbg = False
                resources_path = str(Path(sys.modules[__name__.split(".")[0]].__file__).
                    with_name("res"))
                self._send_stream("stderr",
                    "is_dbstop_if_error.m from imatlab resources folder (%s) is not found on path\n" % (resources_path, ))

            try:
                code_to_run = no_try_code if isdbg else try_code
                self._execute_with_debug_detection(code_to_run, nargout=0)
            except (SyntaxError, MatlabExecutionError, KeyboardInterrupt):
                status = "error"
            except EngineError as engine_error:
                # Check whether the engine died.
                try:
                    self._call("eval", "1")
                except EngineError:
                    self._send_stream(
                        "stderr",
                        "Please quit the front-end (Ctrl-D from the console "
                        "or qtconsole) to shut the kernel down.\n")
                    # We don't want to GC the engines as that'll lead to an
                    # attempt to close an already closed MATLAB during
                    # `__del__`, which raises an uncatchable exception.  So
                    # we just keep them around instead.
                    self._dead_engines.append(self._engine)
                    self._engine = matlab.engine.start_matlab()
                else:
                    raise engine_error

        elif os.name == "nt":
            out = StringIO()
            err = StringIO()
                
            try:
                # call wrapped in try / catch if we're not debugging
                isdbg = self._engine.is_dbstop_if_error()
            except (SyntaxError, MatlabExecutionError, KeyboardInterrupt):
                isdbg = False
                resources_path = str(Path(sys.modules[__name__.split(".")[0]].__file__).
                    with_name("res"))
                self._send_stream("stderr",
                    "is_dbstop_if_error.m from imatlab resources folder (%s) is not found on path\n" % (resources_path, ))

            try:
                if isdbg:
                    self._call("eval", no_try_code, nargout=0, stdout=out, stderr=err)
                else:
                    self._call("eval", try_code, nargout=0, stdout=out, stderr=err)
            except (SyntaxError, MatlabExecutionError, KeyboardInterrupt):
                status = "error"
            except EngineError as engine_error:
                # Check whether the engine died.
                try:
                    self._call("eval", "1")
                except EngineError:
                    self._send_stream(
                        "stderr",
                        "Please quit the front-end (Ctrl-D from the console "
                        "or qtconsole) to shut the kernel down.\n")
                    # We don't want to GC the engines as that'll lead to an
                    # attempt to close an already closed MATLAB during
                    # `__del__`, which raises an uncatchable exception.  So
                    # we just keep them around instead.
                    self._dead_engines.append(self._engine)
                    self._engine = matlab.engine.start_matlab()
                else:
                    raise engine_error
            finally:
                for name, buf in [("stdout", out), ("stderr", err)]:
                    buf.seek(0, os.SEEK_END)
                    size = buf.tell()
                    if size > 0:
                        self._send_stream(name, buf.getvalue())

        # elif os.name == "nt":
        #     self._send_stream("running nt\n")
        #     try:
        #         out = StringIO()
        #         err = StringIO()
        #         # call wrapped in try / catch if we're not debugging
        #         isdbg = self._engine.is_dbstop_if_error()
        #         if isdbg:
        #             self._call("eval", no_try_code, nargout=0, stdout=out, stderr=err)
        #         else:
        #             self._call("eval", try_code, nargout=0, stdout=out, stderr=err)
        #     except (SyntaxError, MatlabExecutionError, KeyboardInterrupt):
        #         status = "error"
        #     finally:
        #         for name, buf in [("stdout", out), ("stderr", err)]:
        #             self._send_stream(name, buf.getvalue())
        else:
            raise OSError("Unsupported OS")

        self._export_figures()

        # if store_history and code:  # Skip empty lines.
        #     elapsed = time.perf_counter() - start
        #     self._history.append(code, elapsed, status == "ok")
        self._silent = False

        # self.log.error("DONE do_execute command")

        if status == "ok":
            return {"status": status,
                    "execution_count": self.execution_count,
                    "payload": [],
                    "user_expressions": {}}
        elif status == "error":  # The mechanism is Python-specific.
            return {"status": status,
                    "execution_count": self.execution_count,
                    "ename": "",
                    "evalue": "",
                    "traceback": []}

    def _export_figures(self):
        if (self._has_console_frontend
                or not len(self._call("get", 0., "children"))
                or not self._call("which", "imatlab_export_fig")):
            return
        with TemporaryDirectory() as tmpdir:
            cwd = self._call("cd")
            try:
                self._call("cd", tmpdir)
                exported = self._engine.imatlab_export_fig()
            finally:
                self._call("cd", cwd)
            for path in map(Path(tmpdir).joinpath, exported):
                if path.suffix.lower() == ".html":
                    # https://github.com/jupyter/notebook/issues/2287
                    # Delay import, as this is not a dependency otherwise.
                    import notebook
                    if notebook.__version__ == "5.0.0":
                        self._send_stream(
                            "stderr",
                            "Plotly output is not supported with "
                            "notebook==5.0.0.  Please update to a newer "
                            "version.")
                    elif not plotly:
                        self._send_stream(
                            "stderr",
                            "Failed to import both matlab.engine and plotly "
                            "in the same process; plotly output is "
                            "unavailable.")
                    else:
                        self._plotly_init_notebook_mode()
                        self._send_display_data(
                            {"text/html": path.read_text()}, {})
                elif path.suffix.lower() == ".png":
                    self._send_display_data(
                        {"image/png":
                         base64.b64encode(path.read_bytes()).decode("ascii")},
                        {})
                elif path.suffix.lower() in [".jpeg", ".jpg"]:
                    self._send_display_data(
                        {"image/jpeg":
                         base64.b64encode(path.read_bytes()).decode("ascii")},
                        {})
                elif path.suffix.lower() == ".svg":
                    self._send_display_data(
                        # Probably should read the encoding from the file.
                        {"image/svg+xml": path.read_text(encoding="ascii")},
                        {})

    def _plotly_init_notebook_mode(self):
        # Hack into display routine.  Also pretend that the InteractiveShell is
        # initialized as display() is otherwise turned into a no-op.
        with patch.multiple(IPython.core.display,
                            publish_display_data=self._send_display_data), \
             patch.multiple(InteractiveShell,
                            initialized=lambda: True):
            plotly.offline.init_notebook_mode()

    def do_complete(self, code, cursor_pos):
        code = code[:cursor_pos]
        reply = {
            "status": "ok",
            "cursor_start": cursor_pos,
            "cursor_end": cursor_pos,
            "matches": [],
            "metadata": {},
        }

        if cursor_pos > 0:
            # Use
            #
            #     String[] MatlabMCR.mtFindAllTabCompletions(String, int, int)
            #
            # This directly returns a list of completions.  It returns the
            # *previously computed* list of completions for a zero-length
            # input, so only handle the non-zero length case.
            completions = self._eval(
                "cell(com.mathworks.jmi.MatlabMCR().mtFindAllTabCompletions"
                "('{}', {}, 0))"
                .format(code.replace("'", "''"), cursor_pos))
            reply["cursor_start"] -= len(re.search(r"\w*$", code).group())
            reply["matches"] = completions
        
        return reply

    def do_inspect(self, code, cursor_pos, *args, **kwargs):
        try:
            token, = re.findall(r"\b[a-z]\w*(?=\(?\Z)", code[:cursor_pos])
        except ValueError:
            help = ""
        else:
            help = self._engine.help(token)  # Not a builtin.
        return {"status": "ok",
                "found": bool(help),
                "data": {"text/plain": help},
                "metadata": {}}

    def do_history(
            self, hist_access_type, output, raw, session=None, start=None,
            stop=None, n=None, pattern=None, unique=False):
        # return {"history": self._history.as_list}
        return {"status": "ok", "history": []}

    def do_is_complete(self, code):
        # with TemporaryDirectory() as tmpdir:
        #     path = Path(tmpdir, "test_complete.m")
        #     path.write_text(code)
        #     errs = self._call(
        #         "eval",
        #         "feval(@(e) {{e.message}}, checkcode('-m2', '{}'))"
        #         .format(str(path).replace("'", "''")))
        #     # 'Invalid syntax': unmatched brackets.
        #     # 'Parse error': unmatched keywords.
        #     if any(err.startswith(("Invalid syntax at",
        #                            "Parse error at")) for err in errs):
        #         return {"status": "invalid"}
        #     # `mtree` returns a single node tree on parse error (but not
        #     # otherwise -- empty inputs give no nodes, expressions give two
        #     # nodes).  Given that we already excluded (some) errors earlier,
        #     # this likely means incomplete code.
        #     # Using the (non-documented) `mtree` works better than checking
        #     # whether `pcode` successfully generates code as `pcode` refuses
        #     # to generate code for classdefs with a name not matching the file
        #     # name, whereas we actually want to report `classdef foo, end` to
        #     # be reported as complete (so that MATLAB errors at evaluation).
        #     incomplete = self._call(
        #         "eval",
        #         "builtin('numel', mtree('{}', '-file').indices) == 1"
        #         .format(str(path).replace("'", "''")))
        #     if incomplete:
        #         return {"status": "incomplete",
        #                 "indent": ""}  # FIXME
        #     else:
                # return {"status": "complete"}
        return {"status": "complete"}

    def do_shutdown(self, restart):
        self._call("exit", nargout=0)
        if restart:
            self._engine = matlab.engine.start_matlab()
