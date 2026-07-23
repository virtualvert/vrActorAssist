use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ActorInfo {
    pub name: String,
    pub machine_id: String,
    pub latency_ms: u32,
    pub approved: bool,
    pub enabled: bool,
}

/// Tracks known actors by name. `enabled` defaults to true for newly-seen actors,
/// matching director_client_ws.py's actor_enabled dict default of True.
#[derive(Default)]
pub struct ActorRegistry {
    pub actors: HashMap<String, ActorInfo>,
}

impl ActorRegistry {
    pub fn upsert_pending(&mut self, name: &str, machine_id: &str) {
        self.actors.entry(name.to_string()).or_insert(ActorInfo {
            name: name.to_string(),
            machine_id: machine_id.to_string(),
            latency_ms: 0,
            approved: false,
            enabled: true,
        });
    }

    #[allow(dead_code)]
    pub fn mark_approved(&mut self, name: &str) {
        if let Some(a) = self.actors.get_mut(name) {
            a.approved = true;
        }
    }

    /// Updates latency for an approved actor (from STATUS broadcast).
    /// Inserts the actor if not already known, with a placeholder machine_id.
    /// STATUS messages don't carry machine_id — the placeholder is only used
    /// until a PENDING or broadcast fills in the real machine_id.
    pub fn upsert_from_status(&mut self, name: &str, latency_ms: u32) {
        let entry = self.actors.entry(name.to_string()).or_insert(ActorInfo {
            name: name.to_string(),
            machine_id: String::new(),
            latency_ms,
            approved: true,
            enabled: true,
        });
        entry.latency_ms = latency_ms;
        entry.approved = true;
    }

    pub fn remove(&mut self, name: &str) {
        self.actors.remove(name);
    }

    pub fn set_enabled(&mut self, name: &str, enabled: bool) {
        if let Some(a) = self.actors.get_mut(name) {
            a.enabled = enabled;
        }
    }

    pub fn enabled_names(&self) -> Vec<String> {
        self.actors.values().filter(|a| a.approved && a.enabled).map(|a| a.name.clone()).collect()
    }

    #[allow(dead_code)]
    pub fn set_latency(&mut self, name: &str, latency_ms: u32) {
        if let Some(a) = self.actors.get_mut(name) {
            a.latency_ms = latency_ms;
        }
    }

    pub fn all(&self) -> Vec<ActorInfo> {
        self.actors.values().cloned().collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_actor_defaults_to_enabled_and_unapproved() {
        let mut reg = ActorRegistry::default();
        reg.upsert_pending("Actor1", "id-1");
        let a = &reg.actors["Actor1"];
        assert!(a.enabled);
        assert!(!a.approved);
    }

    #[test]
    fn enabled_names_excludes_unapproved() {
        let mut reg = ActorRegistry::default();
        reg.upsert_pending("Actor1", "id-1");
        reg.upsert_pending("Actor2", "id-2");
        reg.mark_approved("Actor1");
        assert_eq!(reg.enabled_names(), vec!["Actor1".to_string()]);
    }

    #[test]
    fn disabled_actor_excluded_from_enabled_names() {
        let mut reg = ActorRegistry::default();
        reg.upsert_pending("Actor1", "id-1");
        reg.mark_approved("Actor1");
        reg.set_enabled("Actor1", false);
        assert!(reg.enabled_names().is_empty());
    }

    #[test]
    fn set_latency_updates_existing_actor_only() {
        let mut reg = ActorRegistry::default();
        reg.upsert_pending("Actor1", "id-1");
        reg.set_latency("Actor1", 42);
        reg.set_latency("NoSuchActor", 999); // must not panic or create an entry
        assert_eq!(reg.actors["Actor1"].latency_ms, 42);
        assert_eq!(reg.actors.len(), 1);
    }

    #[test]
    fn upsert_from_status_inserts_unknown_and_sets_approved() {
        let mut reg = ActorRegistry::default();
        reg.upsert_from_status("Actor1", 42);
        let a = &reg.actors["Actor1"];
        assert!(a.approved);
        assert_eq!(a.latency_ms, 42);
    }
}
