function result = test_debug()
    % Simple function to test debugger behavior
    x = 1;
    y = 2;
    z = x + y;  % We'll set a breakpoint here
    result = z * 10;
    fprintf('Final result: %d\n', result);
end
