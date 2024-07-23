// Copyright © 2024 Pathway

#![warn(clippy::pedantic)]
#![warn(clippy::cargo)]
#![allow(clippy::must_use_candidate)] // too noisy

// FIXME:
#![allow(clippy::missing_errors_doc)]
#![allow(clippy::missing_panics_doc)]

pub mod connectors;
pub mod deepcopy;
pub mod engine;
pub mod external_integration;
pub mod persistence;
pub mod python_api;

mod env;
mod fs_helpers;
mod mat_mul;
mod pipe;
mod timestamp;

