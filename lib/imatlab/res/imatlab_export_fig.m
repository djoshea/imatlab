function exported = imatlab_export_fig(exporter)
    % IMATLAB_EXPORT_FIG Set exporter or export figures for imatlab.
    %
    %   IMATLAB_EXPORT_FIG(exporter)
    %     where exporter is one of
    %       {'', 'fig2plotly', 'print-jpeg', 'print-png'}
    %     sets the current exporter.
    %
    %   exported = IMATLAB_EXPORT_FIG
    %     orders the current figures by number, exports and closes them, and
    %     returns a cell array of exported filenames.

    set_exporter = getenv('IMATLAB_FIGURE_EXPORTER');
    if isempty(set_exporter)
        set_exporter = '';
    end
    valid_exporters = {'', 'fig2plotly', 'print-png', 'print-jpeg', 'print-svg'};

    % determine real screen DPI
    screenDPI = getenv('SCREEN_DPI');
    if ~isempty(screenDPI)
        screenDPI = str2double(screenDPI);
    else
        screenDPI = java.awt.Toolkit.getDefaultToolkit().getScreenResolution();
    end
    if isnan(screenDPI)
        screenDPI = 0;
    end
%     displayDPI = 72;
    
    if exist('exporter', 'var')
        if any(strcmp(exporter, valid_exporters))
            if strcmp(exporter, 'fig2plotly')
                version_delta = ...
                    str2double(strsplit(plotly_version, '.')) - [2, 2, 7];
                if version_delta(find(version_delta, 1)) < 0
                    error('imatlab:unsupportedPlotlyVersion', ...
                          'imatlab requires plotly>=2.2.7.')
                end
            end
            set_exporter = exporter;
            setenv('IMATLAB_FIGURE_EXPORTER', set_exporter);
        else
            error('imatlab:invalidExporter', ...
                  ['known exporters are ', ...
                   strjoin(cellfun(@(c) ['''', c, ''''], valid_exporters, ...
                           'UniformOutput', false), ', ')]);
        end
    else
        children = get(0, 'children');
        [~, idx] = sort([children.Number]);
        children = children(idx);

        % ignore figures marked (these were visible before the kernel executed this block of code)
        mask = true(numel(children), 1);
        for iF = 1:numel(children)
            ud = children(iF).UserData;
            if isstruct(ud)
                if isfield(ud, 'imatlab_ignore') && ud.imatlab_ignore
                    mask(iF) = false;
                    continue;
                end
            end
            if isempty(children(iF).Children)
                % don't save empty plots, which includes the one created by imatlab_pre_execute
                mask(iF) = false;
            end
        end
        children = children(mask);

        switch set_exporter
        case ''
            exported = {};
        case 'fig2plotly'
            exported = cell(1, numel(children));
            for i = 1:numel(children)
                name = tempname('.');
                exported{i} = [name, '.html'];
                try
                    fig2plotly(children(i), 'filename', name, ...
                               'offline', true, 'open', false);
                catch me
                    warning('fig2plotly failed to export a figure');
                    rethrow(me);
                end
                close(children(i));
            end
        case 'print-png'
            exported = cell(1, numel(children));
            for i = 1:numel(children)
                name = tempname('.');
                exported{i} = [name, '.png'];
                % Use screen resolution.
                print(children(i), exported{i}, '-dpng', sprintf('-r%d', screenDPI));
                close(children(i));
            end
        case 'print-svg'
            exported = cell(1, numel(children));
            for i = 1:numel(children)
                name = tempname('.');
                exported{i} = [name, '.svg'];
                % Use screen resolution.
                print(children(i), exported{i}, '-dsvg', sprintf('-r%d', screenDPI));
                close(children(i));
            end
        case 'print-jpeg'
            exported = cell(1, numel(children));
            for i = 1:numel(children)
                name = tempname('.');
                exported{i} = [name, '.jpg'];
                % Use screen resolution.
                print(children(i), name, '-djpeg', sprintf('-r%d', screenDPI));
                close(children(i));
            end
        end
    end
end
