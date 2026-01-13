function [functionNames, functionCodes, remainingCode, errorMsg] = imatlab_extract_functions(code)
    % Extract outer function definitions from MATLAB code using mtree
    %
    % Args:
    %   code: String containing MATLAB code
    %
    % Returns:
    %   functionNames: cell array of function name strings
    %   functionCodes: cell array of function code strings
    %   remainingCode: code with function definitions removed
    %   errorMsg: error message string if parsing failed, empty otherwise

    functionNames = {};
    functionCodes = {};
    remainingCode = code;
    errorMsg = '';

    % Parse code with mtree
    try
        tree = mtree(code, '-com');
    catch ME
        % If parsing fails, return error message
        errorMsg = sprintf('Syntax error in cell code:\n%s\n\nMATLAB parser error: %s', ...
            code, ME.message);
        return;
    end

    % Check if tree is empty
    if isempty(tree) || count(tree) == 0
        return;
    end

    lines = splitlines(code);
    if isempty(lines)
        return;
    end

    linesToRemove = false(size(lines));

    % Use mtfind to get FUNCTION nodes (this is the correct API)
    funcNodes = mtfind(tree, 'Kind', 'FUNCTION');

    % Check if any functions were found
    if isempty(funcNodes) || count(funcNodes) == 0
        return;
    end

    % Get indices of function nodes
    nodeIndices = funcNodes.indices;

    % Iterate through each function node
    for i = 1:length(nodeIndices)
        % Select the specific node
        node = select(tree, nodeIndices(i));

        % Get function name
        if ~isempty(node.Fname)
            funcName = char(string(node.Fname));

            % Get line range (1-indexed)
            startLine = node.lineno;

            % Find the matching 'end' for this function
            endLine = findMatchingEnd(lines, startLine);

            if endLine > 0 && endLine <= length(lines)
                % Extract function code
                funcCode = strjoin(lines(startLine:endLine), newline);

                % Add to results
                functionNames{end+1} = funcName;
                functionCodes{end+1} = char(funcCode);

                % Mark lines for removal
                linesToRemove(startLine:endLine) = true;
            else
                % Found function but couldn't find matching end
                errorMsg = sprintf(['Syntax error: Function ''%s'' on line %d is missing its closing ''end'' keyword.\n\n' ...
                    'Line %d: %s'], funcName, startLine, startLine, lines{startLine});
                return;
            end
        end
    end

    % Build remaining code
    remainingLines = lines(~linesToRemove);
    remainingCode = char(strjoin(remainingLines, newline));
end

function endLine = findMatchingEnd(lines, startLine)
    % Find the matching 'end' for a function starting at startLine
    nestLevel = 1;
    endLine = -1;

    for i = (startLine + 1):length(lines)
        line = strtrim(lines{i});

        % Skip comment lines
        if startsWith(line, '%')
            continue;
        end

        % Check for keywords that increase nesting
        if ~isempty(regexp(line, '^\s*(function|if|for|while|switch|try|parfor|classdef)\s', 'once'))
            nestLevel = nestLevel + 1;
        end

        % Check for 'end' keyword
        if ~isempty(regexp(line, '^\s*end\s*($|;|%|,)', 'once')) || strcmp(line, 'end')
            nestLevel = nestLevel - 1;
            if nestLevel == 0
                endLine = i;
                return;
            end
        end
    end
end
