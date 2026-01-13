"""
MATLAB Language Server Manager

Handles automatic download, setup, and lifecycle management of the
MATLAB Language Server for use in the Jupyter kernel.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

# pygls imports - not used directly, but kept for future reference
# from lsprotocol.types import (
#     DocumentSymbolParams,
#     TextDocumentIdentifier,
#     InitializeParams,
#     ClientCapabilities,
# )


class LanguageServerManager:
    """Manages the MATLAB Language Server instance."""

    # Default configuration
    LS_REPO = "https://github.com/mathworks/MATLAB-language-server.git"
    LS_VERSION = "v1.3.8"

    def __init__(self, log_callback=None):
        """Initialize the language server manager.

        Args:
            log_callback: Optional callback function(message: str) for debug output
        """
        self.log_callback = log_callback
        self._server_process: Optional[subprocess.Popen] = None
        self._protocol: Optional[LanguageServerProtocol] = None
        self._initialized = False
        self._message_id = 0
        self._lock = threading.Lock()

        # Determine installation directory
        self.install_dir = Path.home() / ".imatlab" / "language-server"
        self.server_path = self.install_dir / "out" / "index.js"

    def _log(self, message: str):
        """Log a message via callback if available."""
        if self.log_callback:
            self.log_callback(f"[LSP] {message}")

    def ensure_installed(self) -> bool:
        """Ensure the language server is installed and ready.

        Returns:
            True if server is ready, False if installation failed
        """
        if self.server_path.exists():
            self._log(f"Language server already installed at {self.install_dir}")
            return True

        self._log("Language server not found, installing...")
        return self._install_language_server()

    def _install_language_server(self) -> bool:
        """Download and build the language server.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if git is available
            if shutil.which("git") is None:
                self._log("ERROR: git is not installed. Cannot download language server.")
                return False

            # Check if node/npm is available
            if shutil.which("node") is None or shutil.which("npm") is None:
                self._log("ERROR: Node.js/npm is not installed. Cannot build language server.")
                return False

            # Create installation directory
            self.install_dir.mkdir(parents=True, exist_ok=True)

            # Clone the repository
            self._log(f"Cloning language server from {self.LS_REPO}...")
            result = subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", self.LS_VERSION,
                 self.LS_REPO, str(self.install_dir)],
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                self._log(f"ERROR: Failed to clone repository: {result.stderr}")
                return False

            # Install npm dependencies
            self._log("Installing Node.js dependencies...")
            result = subprocess.run(
                ["npm", "install"],
                cwd=str(self.install_dir),
                capture_output=True,
                text=True,
                timeout=600
            )

            if result.returncode != 0:
                self._log(f"ERROR: npm install failed: {result.stderr}")
                return False

            # Build the language server
            self._log("Building language server...")
            result = subprocess.run(
                ["npm", "run", "compile"],
                cwd=str(self.install_dir),
                capture_output=True,
                text=True,
                timeout=600
            )

            # Note: compile may return non-zero due to missing vite, but core build succeeds
            if not self.server_path.exists():
                self._log(f"ERROR: Build completed but {self.server_path} not found")
                self._log(f"Build output: {result.stdout}")
                self._log(f"Build errors: {result.stderr}")
                return False

            self._log("Language server installed successfully")
            return True

        except subprocess.TimeoutExpired:
            self._log("ERROR: Installation timed out")
            return False
        except Exception as e:
            self._log(f"ERROR: Installation failed: {e}")
            return False

    def start(self) -> bool:
        """Start the language server process.

        Returns:
            True if started successfully, False otherwise
        """
        self._log("=== LanguageServerManager.start() called ===")

        if self._server_process is not None:
            self._log("Language server already running")
            return True

        self._log("Checking if language server is installed...")
        if not self.ensure_installed():
            self._log("Cannot start language server: installation failed")
            return False
        self._log("Language server installation verified")

        try:
            # Start the language server as a subprocess
            # Use --matlabConnectionTiming=onDemand so it connects when needed
            self._log(f"Starting language server subprocess: node {self.server_path}")
            self._server_process = subprocess.Popen(
                ["node", str(self.server_path), "--stdio", "--matlabConnectionTiming=onDemand"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.install_dir)
            )
            self._log("Subprocess created (with --matlabConnectionTiming=onDemand), waiting 1 second...")

            # Give it a moment to start
            time.sleep(1)

            # Check if process is still running
            self._log("Checking if process is still alive...")
            if self._server_process.poll() is not None:
                stderr = self._server_process.stderr.read().decode() if self._server_process.stderr else ""
                self._log(f"ERROR: Language server process exited immediately: {stderr}")
                self._server_process = None
                return False

            self._log("Language server process is running, initializing protocol...")

            # Initialize the LSP connection
            result = self._initialize_protocol()
            self._log(f"Protocol initialization returned: {result}")
            return result

        except Exception as e:
            self._log(f"ERROR: Failed to start language server: {e}")
            self._server_process = None
            return False

    def _initialize_protocol(self) -> bool:
        """Initialize the LSP protocol with the server.

        Returns:
            True if initialization succeeded
        """
        try:
            self._log("_initialize_protocol: Building init params...")
            # Send initialize request
            init_params = {
                "processId": os.getpid(),
                "rootUri": None,
                "capabilities": {
                    "textDocument": {
                        "documentSymbol": {
                            "hierarchicalDocumentSymbolSupport": True
                        }
                    }
                }
            }

            self._log("_initialize_protocol: Sending initialize request...")
            response = self._send_request("initialize", init_params)
            if response is None:
                self._log("ERROR: Initialize request failed")
                return False

            self._log("_initialize_protocol: Initialize request succeeded, sending initialized notification...")
            # Send initialized notification
            self._send_notification("initialized", {})

            self._initialized = True
            self._log("Language server initialized successfully")
            return True

        except Exception as e:
            self._log(f"ERROR: Protocol initialization failed: {e}")
            import traceback
            self._log(traceback.format_exc())
            return False

    def _send_request(self, method: str, params: Any, timeout: float = 10) -> Optional[Dict]:
        """Send a JSON-RPC request and wait for response.

        Args:
            method: LSP method name
            params: Request parameters
            timeout: Timeout in seconds (default 10)

        Returns:
            Response dict or None if failed
        """
        self._log(f"_send_request: method={method}, timeout={timeout}s")

        if self._server_process is None or self._server_process.poll() is not None:
            self._log("ERROR: Language server not running")
            return None

        with self._lock:
            self._message_id += 1
            message_id = self._message_id

        request = {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": method,
            "params": params
        }

        try:
            # Serialize and send request
            self._log(f"_send_request: Serializing request id={message_id}...")
            request_json = json.dumps(request)
            message = f"Content-Length: {len(request_json)}\r\n\r\n{request_json}"

            self._log(f"_send_request: Writing to stdin...")
            self._server_process.stdin.write(message.encode())
            self._server_process.stdin.flush()
            self._log(f"_send_request: Request sent, reading response...")

            # Read response
            result = self._read_response(message_id, timeout=timeout)
            self._log(f"_send_request: Response received: {result is not None}")
            return result

        except Exception as e:
            self._log(f"ERROR: Failed to send request {method}: {e}")
            return None

    def _send_notification(self, method: str, params: Any):
        """Send a JSON-RPC notification (no response expected).

        Args:
            method: LSP method name
            params: Notification parameters
        """
        if self._server_process is None:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }

        try:
            notification_json = json.dumps(notification)
            message = f"Content-Length: {len(notification_json)}\r\n\r\n{notification_json}"
            self._server_process.stdin.write(message.encode())
            self._server_process.stdin.flush()
        except Exception as e:
            self._log(f"ERROR: Failed to send notification {method}: {e}")

    def _drain_notifications(self, max_wait: float = 1.0):
        """Read and discard any pending notifications from the server.

        Args:
            max_wait: Maximum time to wait for notifications (seconds)
        """
        if self._server_process is None or self._server_process.stdout is None:
            return

        import select
        drained_count = 0
        start_time = time.time()

        while time.time() - start_time < max_wait:
            try:
                # Check if there's data available (non-blocking)
                ready, _, _ = select.select([self._server_process.stdout], [], [], 0.1)
                if not ready:
                    # No more data available
                    break

                # Read the message
                header = self._server_process.stdout.readline().decode().strip()
                if not header.startswith("Content-Length:"):
                    continue

                content_length = int(header.split(":")[1].strip())
                self._server_process.stdout.readline()  # blank line
                content = self._server_process.stdout.read(content_length).decode()
                message = json.loads(content)

                self._log(f"_drain_notifications: Discarded message: {message.get('method', 'unknown')}")
                drained_count += 1

            except Exception as e:
                self._log(f"_drain_notifications: Error: {e}")
                break

        self._log(f"_drain_notifications: Drained {drained_count} notification(s)")

    def _read_response(self, expected_id: int, timeout: float = 10) -> Optional[Dict]:
        """Read and parse a JSON-RPC response.

        Args:
            expected_id: Expected message ID
            timeout: Timeout in seconds

        Returns:
            Response dict or None
        """
        self._log(f"_read_response: Waiting for response id={expected_id}, timeout={timeout}s")

        if self._server_process is None or self._server_process.stdout is None:
            self._log("_read_response: Server process or stdout is None")
            return None

        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Check if there's data available on stdout before reading
                import select
                ready, _, _ = select.select([self._server_process.stdout], [], [], 1.0)
                if not ready:
                    self._log(f"_read_response: No data on stdout after 1s, continuing... (elapsed: {time.time() - start_time:.1f}s)")
                    continue

                # Read Content-Length header
                self._log(f"_read_response: Reading header line... (elapsed: {time.time() - start_time:.1f}s)")
                header = self._server_process.stdout.readline().decode().strip()
                if not header.startswith("Content-Length:"):
                    self._log(f"_read_response: Skipping non-Content-Length header: {header[:50]}")
                    continue

                content_length = int(header.split(":")[1].strip())
                self._log(f"_read_response: Got Content-Length: {content_length}")

                # Read blank line
                self._server_process.stdout.readline()

                # Read content
                self._log(f"_read_response: Reading {content_length} bytes of content...")
                content = self._server_process.stdout.read(content_length).decode()
                message = json.loads(content)
                self._log(f"_read_response: Parsed message with id={message.get('id')}")

                # Check if this is our response
                if message.get("id") == expected_id:
                    if "error" in message:
                        self._log(f"ERROR: Server returned error: {message['error']}")
                        return None
                    self._log(f"_read_response: Found matching response!")
                    return message.get("result")
                else:
                    # Log what the message actually contains
                    self._log(f"_read_response: Message id mismatch (got {message.get('id')}, want {expected_id})")
                    self._log(f"_read_response: Message content: {json.dumps(message)[:500]}")
                    self._log(f"_read_response: Continuing to read...")

            except Exception as e:
                self._log(f"ERROR: Failed to read response: {e}")
                import traceback
                self._log(traceback.format_exc())
                return None

        self._log(f"ERROR: Timeout waiting for response to message {expected_id}")
        return None

    def get_document_symbols(self, code: str, uri: str = None) -> Optional[List[Dict]]:
        """Get document symbols from the language server.

        Args:
            code: MATLAB code to analyze
            uri: Document URI (if None, a temp file will be created)

        Returns:
            List of symbol dictionaries or None if failed
        """
        # Test if callback works - call it directly
        if self.log_callback:
            self.log_callback("=== ENTERED get_document_symbols ===")

        self._log(f"get_document_symbols: Called with code length={len(code)}")

        if not self._initialized:
            self._log("ERROR: Language server not initialized")
            return None

        # Create a temporary file for the code
        # The language server needs a real file on disk
        import tempfile
        temp_file = None
        try:
            # Create temp file with .m extension
            with tempfile.NamedTemporaryFile(mode='w', suffix='.m', delete=False) as f:
                temp_file = f.name
                f.write(code)

            # Convert to file:// URI
            from pathlib import Path
            file_uri = Path(temp_file).as_uri()
            self._log(f"get_document_symbols: Created temp file: {file_uri}")

            # Send textDocument/didOpen notification
            self._log("get_document_symbols: Sending textDocument/didOpen notification...")
            self._send_notification("textDocument/didOpen", {
                "textDocument": {
                    "uri": file_uri,
                    "languageId": "matlab",
                    "version": 1,
                    "text": code
                }
            })
            self._log("get_document_symbols: didOpen sent")

            # Give server time to process didOpen and send back diagnostics
            # We need to wait for publishDiagnostics before requesting symbols
            self._log("get_document_symbols: Sleeping 2s to let didOpen complete...")
            time.sleep(2.0)

            # Drain any pending notifications (telemetry, diagnostics, etc.)
            self._log("get_document_symbols: Draining pending notifications...")
            self._drain_notifications()

            # Request document symbols
            self._log("get_document_symbols: Sending textDocument/documentSymbol request...")
            response = self._send_request("textDocument/documentSymbol", {
                "textDocument": {
                    "uri": file_uri
                }
            }, timeout=30)  # Longer timeout in case MATLAB needs to connect
            self._log(f"get_document_symbols: documentSymbol request returned: {response is not None}")

            # Close the document
            self._log("get_document_symbols: Sending textDocument/didClose notification...")
            self._send_notification("textDocument/didClose", {
                "textDocument": {
                    "uri": file_uri
                }
            })
            self._log("get_document_symbols: didClose sent, returning response")

            return response

        except Exception as e:
            self._log(f"ERROR: Failed to get document symbols: {e}")
            import traceback
            self._log(traceback.format_exc())
            return None
        finally:
            # Clean up temp file
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                    self._log(f"get_document_symbols: Cleaned up temp file")
                except Exception as e:
                    self._log(f"get_document_symbols: Failed to clean up temp file: {e}")

    def get_completions(self, code: str, line: int, character: int, uri: str = None) -> Optional[List[Dict]]:
        """Get completions from the language server.

        Args:
            code: MATLAB code to analyze
            line: Line number (0-indexed)
            character: Character position in line (0-indexed)
            uri: Document URI (if None, a temp file will be created)

        Returns:
            List of completion items or None if failed
        """
        self._log(f"get_completions: line={line}, char={character}")

        if not self._initialized:
            self._log("ERROR: Language server not initialized")
            return None

        # Create a temporary file for the code
        import tempfile
        temp_file = None
        try:
            # Create temp file with .m extension
            with tempfile.NamedTemporaryFile(mode='w', suffix='.m', delete=False) as f:
                temp_file = f.name
                f.write(code)

            # Convert to file:// URI
            from pathlib import Path
            file_uri = Path(temp_file).as_uri()
            self._log(f"get_completions: Created temp file: {file_uri}")

            # Send textDocument/didOpen notification
            self._log("get_completions: Sending textDocument/didOpen...")
            self._send_notification("textDocument/didOpen", {
                "textDocument": {
                    "uri": file_uri,
                    "languageId": "matlab",
                    "version": 1,
                    "text": code
                }
            })

            # Give server a moment to process
            time.sleep(0.5)

            # Drain any pending notifications
            self._drain_notifications(max_wait=0.5)

            # Request completions
            self._log("get_completions: Sending textDocument/completion request...")
            response = self._send_request("textDocument/completion", {
                "textDocument": {
                    "uri": file_uri
                },
                "position": {
                    "line": line,
                    "character": character
                }
            }, timeout=5)
            self._log(f"get_completions: Response received: {response is not None}")

            # Close the document
            self._send_notification("textDocument/didClose", {
                "textDocument": {
                    "uri": file_uri
                }
            })

            return response

        except Exception as e:
            self._log(f"ERROR: Failed to get completions: {e}")
            import traceback
            self._log(traceback.format_exc())
            return None
        finally:
            # Clean up temp file
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except Exception as e:
                    self._log(f"Failed to clean up temp file: {e}")

    def stop(self):
        """Stop the language server process."""
        if self._server_process is None:
            return

        try:
            # Send shutdown request
            if self._initialized:
                self._send_request("shutdown", {})
                self._send_notification("exit", {})

            # Wait for process to exit
            self._server_process.wait(timeout=5)

        except subprocess.TimeoutExpired:
            self._log("Language server did not exit gracefully, killing...")
            self._server_process.kill()
        except Exception as e:
            self._log(f"ERROR: Failed to stop language server: {e}")
        finally:
            self._server_process = None
            self._initialized = False
            self._log("Language server stopped")

    def __del__(self):
        """Cleanup on deletion."""
        self.stop()
