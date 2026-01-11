function tf = is_desktop_visible()
    % Check if MATLAB desktop window is currently visible
    % Returns true if desktop is shown, false otherwise

    % First check if desktop is available at all
    if ~usejava('desktop')
        tf = false;
        return;
    end

    try
        % Try to get the desktop frame and check if it's visible
        desktop = com.mathworks.mde.desk.MLDesktop.getInstance;
        if ~isempty(desktop)
            mainFrame = desktop.getMainFrame;
            if ~isempty(mainFrame)
                tf = mainFrame.isVisible();
                return;
            end
        end
    catch
        % If Java desktop interface fails, fall back to usejava
    end

    % Fallback: if we can't determine visibility, assume it matches usejava
    tf = usejava('desktop');
end
