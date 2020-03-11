function imatlab_post_execute()
    % this will be called by the imatlab kernel after executing has finished

    %fprintf('imatlab_post_execute()\n');
    setenv('JUPYTER_CURRENTLY_EXECUTING');
    set(0, 'DefaultFigureVisible', 'on');
end