# Requirements and Steps:
**1. Python 3.10 or greater**
   
**2. MSVC v143 - VS 2022 C++ x64/x86 build tools**
[https://visualstudio.microsoft.com/visual-cpp-build-tools/] \
Choose Desktop development with C++ \
In Optional select
* MSVC v143 - VS 2022 C++ x64/x86 build tools
* C++ ATL & C++ MFC
* C++ Cmake tools for Windows

**3. Rust compiler**
[https://www.rust-lang.org/tools/install]
Using rustup \
Proceed with standard installation. \
Make sure that the default host triple is `x86_64-pc-windows-msvc`

**Install Maturin using python** \
`pip install maturin`

**3. Strawberry Perl** \
[https://strawberryperl.com/]
**4. cmake for windows** \
[https://cmake.org/download/]

# To start building wheel files:
Run `maturin build` in pathway-0.13.0 directory
