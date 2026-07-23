// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod config;
mod protocol;
mod ws_client;

fn main() {
  app_lib::run();
}
