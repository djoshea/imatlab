if __name__ == "__main__":
    from ipykernel.kernelapp import IPKernelApp
    from ._kernel import MatlabKernel

    # Optional debugpy support
    # Uncomment to enable debugging:
    # import debugpy
    # debugpy.listen(5678)
    # print("Waiting for debugger attach in main")
    # debugpy.wait_for_client()
    # debugpy.breakpoint()

    IPKernelApp.launch_instance(kernel_class=MatlabKernel)
