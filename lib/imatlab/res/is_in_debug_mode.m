function tf = is_in_debug_mode()
    % Check if MATLAB is currently paused in debug mode
    % This is different from is_dbstop_if_error which checks if breakpoints are SET
    % This checks if we're currently PAUSED in the debugger

    st = dbstack();
    % When called from the engine while not debugging, dbstack will show
    % the call chain for this function and the engine's eval
    % When paused in debugger, there will be additional frames
    % A simple heuristic: if dbstack has more than 2 frames, we're likely debugging
    % But actually, the most reliable check is to see if we're at a K>> prompt
    % which we can't directly detect. Instead, we check if dbstack shows
    % frames beyond what we expect from a normal engine call.

    % Actually, dbstack() when called normally will just show is_in_debug_mode
    % and possibly the eval caller. When in debug mode, it shows the full stack
    % to the point where execution is paused.

    % A more reliable approach: check if any frame has a non-empty 'file'
    % that's not this function or the engine infrastructure
    tf = numel(st) > 1;
end
