import debugpy 

if __name__ == "__main__":
    from ipykernel.kernelapp import IPKernelApp
    from ._kernel import MatlabKernel

    # debugpy.listen(5678) # ensure that this port is the same as the one in your launch.json
    # print("Waiting for debugger attach in main")
    # debugpy.wait_for_client()
    # debugpy.breakpoint()
    # print('break on this line')

    IPKernelApp.launch_instance(kernel_class=MatlabKernel)
