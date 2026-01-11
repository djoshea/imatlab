# Claude Development Guide for imatlab

This document contains workflow notes for developing and debugging the imatlab Jupyter kernel, particularly for VSCode notebook integration.

## Project Structure

- `lib/imatlab/_kernel.py` - Main kernel implementation (MatlabKernel class)
- `lib/imatlab/res/*.m` - MATLAB helper functions loaded into MATLAB's path
- `test_debug.m` - Test script for debugging scenarios

## Development Environment Setup

### Installing imatlab in Editable Mode

Use `uv` (not pip) to install imatlab in editable mode for live development:

```bash
cd ~/npl/proj
uv add --editable /Users/djoshea/npl/imatlab
```

This makes changes to the source code immediately available without reinstalling.

### Installing/Reinstalling the Jupyter Kernel Spec

After making changes to the kernel code, you need to:

1. **Clear Python cache** (important!):
```bash
find /Users/djoshea/npl/imatlab -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find /Users/djoshea/npl/imatlab -type f -name "*.pyc" -delete 2>/dev/null
```

2. **Reinstall kernel spec**:
```bash
source ~/npl/proj/.venv/bin/activate
jupyter kernelspec uninstall imatlab -y
python -m imatlab install --prefix ~/npl/proj/.venv
```

3. **Verify installation**:
```bash
jupyter kernelspec list
```

Should show: `imatlab    /Users/djoshea/npl/proj/.venv/share/jupyter/kernels/imatlab`

### Complete Reinstall Script

Combine all steps:
```bash
find /Users/djoshea/npl/imatlab -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
find /Users/djoshea/npl/imatlab -type f -name "*.pyc" -delete 2>/dev/null; \
source ~/npl/proj/.venv/bin/activate && \
jupyter kernelspec uninstall imatlab -y && \
python -m imatlab install --prefix ~/npl/proj/.venv && \
echo "Done - restart kernel in VSCode"
```

## VSCode Notebook Integration

### How VSCode Uses Jupyter Kernels

1. VSCode's Jupyter extension discovers kernels via `jupyter kernelspec list`
2. The kernel spec (`kernel.json`) tells VSCode:
   - Which Python interpreter to use
   - Command line arguments
   - Environment variables
   - Display name

3. For each notebook, VSCode launches a separate kernel process

### Selecting the Kernel in VSCode

1. Open a `.ipynb` file in VSCode
2. Click the kernel picker (top right)
3. Select "MATLAB" - should show path: `~/npl/proj/.venv/bin/python`

### Restarting the Kernel

**Important:** After reinstalling the kernel spec or making code changes, you MUST restart the kernel in VSCode:

1. Click kernel picker → "Restart Kernel"
2. Or use Command Palette (Cmd+Shift+P) → "Restart Kernel"

The old kernel process keeps running with old code until restarted!

## Adding Environment Variables to the Kernel

Edit the kernel spec file directly:
```bash
vim ~/npl/proj/.venv/share/jupyter/kernels/imatlab/kernel.json
```

Add an `env` section:
```json
{
 "argv": [
  "/Users/djoshea/npl/proj/.venv/bin/python",
  "-Xfrozen_modules=off",
  "-m",
  "imatlab",
  "-f",
  "{connection_file}"
 ],
 "display_name": "MATLAB",
 "language": "matlab",
 "env": {
  "IMATLAB_DEBUG": "1"
 }
}
```

**Note:** Reinstalling the kernel spec will overwrite this file, so you'll need to re-add the `env` section after each reinstall.

## Debug Output

### Enabling Debug Output

The `IMATLAB_DEBUG` environment variable controls debug output:
- Set to `"1"`, `"true"`, or `"yes"` to enable
- Any other value or unset to disable

Debug messages appear in notebook cell output via `self._debug(message)`.

### Adding Debug Messages in Code

```python
self._debug("Your debug message here")
```

This only outputs when `IMATLAB_DEBUG` is enabled (checked in `__init__`).

### Viewing Kernel Logs

**In VSCode:**
- Output panel: View → Output (Cmd+Shift+U)
- Select "Jupyter" from the dropdown
- Shows kernel startup/shutdown, but NOT our debug messages

**Our debug messages:**
- Appear directly in notebook cell output (stderr stream)
- Only when `IMATLAB_DEBUG=1`

## Testing Debug Mode Issues

### Test Setup

1. Create a test MATLAB function:
```matlab
function result = test_debug()
    x = 1;
    y = 2;
    z = x + y;  % Set breakpoint here
    result = z * 10;
    fprintf('Final result: %d\n', result);
end
```

2. In a notebook cell:
```matlab
addpath('/Users/djoshea/npl/imatlab')
dbstop in test_debug at 5
result = test_debug()
```

3. MATLAB Desktop will enter debug mode at line 5
4. The kernel polls every 2s to detect when debugging completes
5. Type `dbquit` in MATLAB Desktop to exit
6. Cell should complete successfully

### Expected Debug Output

With `IMATLAB_DEBUG=1`:
```
DEBUG: do_execute called with code: addpath...
DEBUG: Probing MATLAB responsiveness...
DEBUG: MATLAB is responsive to probe
DEBUG: Checking if still in debug mode...
DEBUG: is_in_debug_mode returned: True
DEBUG: In debug mode, attempting to show desktop...
DEBUG: Desktop command sent
DEBUG: Probing MATLAB responsiveness...
(continues until dbquit)
DEBUG: Future marked done, getting result
DEBUG: future.result() raised EngineError (likely from debugging): std::exception
DEBUG: Treating as successful completion since future is done
DEBUG: _execute_with_debug_detection returned successfully
DEBUG: About to export figures
DEBUG: Figures exported
DEBUG: Returning status: ok
```

## Common Issues and Solutions

### Cell Hangs After Making Changes

**Problem:** Kernel still using old code
**Solution:** Restart kernel in VSCode

### Debug Messages Don't Appear

**Problem:** Environment variable not set or kernel not restarted
**Solution:**
1. Check kernel.json has `env` section with `IMATLAB_DEBUG: "1"`
2. Restart kernel

### "Module not found" Errors

**Problem:** imatlab not installed or wrong environment
**Solution:**
```bash
cd ~/npl/proj
uv add --editable /Users/djoshea/npl/imatlab
```

### Changes to .m Files Not Taking Effect

**Problem:** MATLAB has cached the old files
**Solution:** In MATLAB Desktop or a notebook cell:
```matlab
clear functions
rehash toolboxcache
```

### Kernel Spec Changes Ignored

**Problem:** VSCode cached the old kernel spec
**Solution:**
1. Reinstall kernel spec
2. Reload VSCode window: Cmd+Shift+P → "Developer: Reload Window"

## Architecture Notes

### Async Execution with Debug Detection

The `_execute_with_debug_detection` method:

1. Launches MATLAB code execution asynchronously (`background=True`)
2. Returns a `Future` object immediately
3. Polls `future.done()` every 0.1 seconds
4. Every 2 seconds, probes MATLAB with a quick test command
5. If probe succeeds and `is_in_debug_mode()` returns `True`:
   - Auto-shows desktop once per execution
   - Continues waiting
6. When `future.done()` becomes `True`:
   - Calls `future.result()` to get result
   - If `EngineError` raised, treats as success (common after debugging)
   - Returns control to notebook

### Why This Works

**Before:** Synchronous `eval()` blocked forever when debugging completed but MATLAB engine had internal state issues.

**After:** Async execution + polling detects completion independently of the Future's state. If MATLAB is responsive and not in debug mode, we know execution finished.

### MATLAB Helper Functions

- `is_dbstop_if_error.m` - Checks if `dbstop if error` is set
- `is_in_debug_mode.m` - Uses `dbstack()` to detect if currently in debugger
- `is_desktop_visible.m` - Checks if MATLAB desktop window is visible
- `imatlab_pre_execute.m` - Setup before each cell execution
- `imatlab_post_execute.m` - Cleanup after each cell execution

## Git Workflow

Current work is on the `fix-debug-mode-completion` branch:

```bash
# Check current branch
git branch

# View commits
git log --oneline

# Create new commits
git add -A
git commit -m "Description

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

## Quick Reference Commands

### Full Development Cycle
```bash
# 1. Make changes to code
vim lib/imatlab/_kernel.py

# 2. Clear cache and reinstall
find /Users/djoshea/npl/imatlab -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find /Users/djoshea/npl/imatlab -type f -name "*.pyc" -delete 2>/dev/null
source ~/npl/proj/.venv/bin/activate
jupyter kernelspec uninstall imatlab -y
python -m imatlab install --prefix ~/npl/proj/.venv

# 3. Restart kernel in VSCode

# 4. Test changes
```

### Enable Debug Output
```bash
# Add to kernel.json after reinstalling:
{
  ...
  "env": {
    "IMATLAB_DEBUG": "1"
  }
}
```

### Test Debug Mode Scenario
```matlab
% In notebook cell:
addpath('/Users/djoshea/npl/imatlab')
dbstop in test_debug at 5
result = test_debug()

% MATLAB Desktop appears, shows line 5
% Type in MATLAB Desktop:
dbquit

% Cell should complete successfully
```

## Troubleshooting Checklist

When something doesn't work:

- [ ] Cleared Python cache?
- [ ] Reinstalled kernel spec?
- [ ] Restarted kernel in VSCode?
- [ ] Correct kernel selected (shows venv path)?
- [ ] Environment variables set in kernel.json?
- [ ] Debug messages enabled (if needed)?
- [ ] MATLAB Desktop visible (for debugging tests)?
- [ ] MATLAB path includes imatlab/res directory?

## Contact & Context

This guide was created during a debugging session to fix the issue where VSCode notebook cells would hang after exiting the MATLAB debugger via `dbquit`. The solution involved implementing async execution with polling and proper error handling for `EngineError` raised after debugging completes.
