// Copyright © 2024 Pathway

use std::mem;
use std::{io, os::windows};
use winapi::shared::cfg;
use winapi::um::winnt::HANDLE as RawHandle;
use winapi::ctypes::c_void;
use libc::{pipe as libcpipe, O_BINARY};
use std::io::{Error};

#[cfg(unix)]
use std::os::fd::{AsFd, AsRawFd, OwnedFd};

use std::os::windows::io::{AsHandle, AsRawHandle, FromRawHandle, OwnedHandle};

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

#[derive(Debug)]
pub struct Pipe {
    pub reader: OwnedHandle,
    pub writer: OwnedHandle,
}


use std::ptr::null_mut;

fn i32_to_owned_handle(handle: i32) -> OwnedHandle {
    // Safety: Ensure the handle is valid and not null before converting
    if handle == 0 {
        panic!("Invalid handle value");
    }
    unsafe { OwnedHandle::from_raw_handle(handle as *mut _) }
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

/*
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
*/



/*
fn set_non_blocking(fd: impl AsFd) -> io::Result<()> {
    let fd = fd.as_fd();
    let flags = fcntl(fd.as_raw_fd(), FcntlArg::F_GETFL)?;
    let flags = OFlag::from_bits_retain(flags);
    fcntl(fd.as_raw_fd(), FcntlArg::F_SETFL(flags | OFlag::O_NONBLOCK))?;
    Ok(())
}
*/
/*
#[cfg_attr(target_os = "linux", allow(dead_code))]
fn set_cloexec(fd: impl AsFd) -> io::Result<()> {
    let fd = fd.as_fd();
    let flags = fcntl(fd.as_raw_fd(), FcntlArg::F_GETFD)?;
    let flags = FdFlag::from_bits_retain(flags);
    fcntl(
        fd.as_raw_fd(),
        FcntlArg::F_SETFD(flags | FdFlag::FD_CLOEXEC),
    )?;
    Ok(())
}*/

pub fn fpipe(
) -> std::result::Result<(std::os::windows::io::OwnedHandle, std::os::windows::io::OwnedHandle), Error> {
    let mut fds = mem::MaybeUninit::<[libc::c_int; 2]>::uninit();

    #[cfg(unix)]
    let res = unsafe { libcpipe(fds.as_mut_ptr().cast()) };

    #[cfg(windows)]
    let res = unsafe { libcpipe(fds.as_mut_ptr().cast(),4096, O_BINARY) };
    
 //   Error::result(res)?;
    let [read, write] = unsafe { fds.assume_init() };

    let rd=i32_to_owned_handle(read);
    let wt=i32_to_owned_handle(write);

    Ok((rd, wt))
}



pub fn pipe(reader_type: ReaderType, writer_type: WriterType) -> io::Result<Pipe> {
    cfg_if! {
        if #[cfg(target_os = "linux")] {
            let (reader, writer) = unistd::pipe2(OFlag::O_CLOEXEC)?;
        } else {
            let (reader, writer) = fpipe()?;
        //    set_cloexec(&reader)?;
        //    set_cloexec(&writer)?;
        }
    }
/*
    if let ReaderType::NonBlocking = reader_type {
        set_non_blocking(&reader)?;
    }

    if let WriterType::NonBlocking = writer_type {
        set_non_blocking(&writer)?;
    }
*/
    Ok(Pipe { reader, writer })
}
