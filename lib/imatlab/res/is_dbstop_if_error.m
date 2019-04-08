function tf = is_dbstop_if_error()
    s = dbstatus('');
    if isempty(s)
        tf = false;
    else
        conds = {s.cond};
        tf = ismember('error', conds);
    end
end
        
