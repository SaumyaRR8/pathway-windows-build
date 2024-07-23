// Copyright © 2024 Pathway

use std::io;
use winapi::um::winnt::HANDLE as RawHandle;
use winapi::ctypes::c_void;

use cfg_if::cfg_if;
use winapi::um::handleapi::INVALID_HANDLE_VALUE;

#[cfg(unix)]
use nix::unistd;

#[cfg(unix)]
use nix::fcntl::{fcntl, FcntlArg, FdFlag, OFlag};

#[allow(dead_code)]
#[derive(Debug, Clone, Copy)]
pub enum ReaderType {
    Blocking,
    NonBlocking,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Copy)]
pub enum WriterType {
    Blocking,
    NonBlocking,
}



// fn set_non_blocking(fd: impl AsFd) -> io::Result<()> {
//     let fd = fd.as_fd();
//     let flags = fcntl(fd.as_raw_fd(), FcntlArg::F_GETFL)?;
//     let flags = OFlag::from_bits_retain(flags);
//     fcntl(fd.as_raw_fd(), FcntlArg::F_SETFL(flags | OFlag::O_NONBLOCK))?;
//     Ok(())
// }

// #[cfg_attr(target_os = "linux", allow(dead_code))]
// fn set_cloexec(fd: impl AsFd) -> io::Result<()> {
//     let fd = fd.as_fd();
//     let flags = fcntl(fd.as_raw_fd(), FcntlArg::F_GETFD)?;
//     let flags = FdFlag::from_bits_retain(flags);
//     fcntl(
//         fd.as_raw_fd(),
//         FcntlArg::F_SETFD(flags | FdFlag::FD_CLOEXEC),
//     )?;
//     Ok(())
// }


pub fn pipe(reader_type: ReaderType, writer_type: WriterType) -> io::Result<(RawHandle, RawHandle)> {
    cfg_if! {
        if #[cfg(target_os = "linux")] {
            let (reader, writer) = unistd::pipe2(OFlag::O_CLOEXEC)?;
        } else if #[cfg(target_os = "windows")] {
            let mut read_handle: RawHandle = INVALID_HANDLE_VALUE;
            let mut write_handle: RawHandle = INVALID_HANDLE_VALUE;
            unsafe {
                if pipe(ReaderType::Blocking, WriterType::Blocking).is_ok() {
                    return Err(io::Error::last_os_error());
                }
            }
        } else {
            return Err(io::Error::new(io::ErrorKind::Other, "Unsupported platform"));
        }
    }

    // Windows-specific or cross-platform post-creation adjustments
    // For example, setting non-blocking mode if required

    Ok((read_handle, write_handle))
}