function imatlab_pre_execute()
    % this will be called by the imatlab kernel before executing a block

    %fprintf('imatlab_pre_execute()\n');
    setenv('JUPYTER_CURRENTLY_EXECUTING', '1');

    exporter = getenv('IMATLAB_FIGURE_EXPORTER');
    if strcmp(exporter, '')
        % no exporter set, show figures as they are generated
        set(0, 'DefaultFigureVisible', 'on');
    else
        % exporter set, hide figures for export and mark existing figures to ignore
        children = get(0, 'children');
        for iF = 1:numel(children)
            if strcmp(children(iF).HandleVisibility, 'on')
                if strcmp(children(iF).Visible, 'on')
                    children(iF).UserData = struct('imatlab_ignore', true);
                else
                    close(children(iF));
                end
            end
        end
        set(0, 'DefaultFigureVisible', 'off');

        % ensure that new plot commands go in a new figure
        figure();
    end

end