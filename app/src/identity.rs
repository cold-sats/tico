//! Display-only identity: never used for storage, login state, or update routing.
pub fn tray_label(name: &str, company: &str, label: &str) -> Option<String> {
    if company.is_empty() {
        return None;
    }
    if !label.is_empty() {
        return Some(label.to_ascii_uppercase());
    }
    // Ignore the product suffix so names such as "Acme Tico" remain recognizable.
    let words: Vec<_> = name.split(|c: char| !c.is_alphanumeric())
        .filter(|word| !word.is_empty() && !word.eq_ignore_ascii_case("tico"))
        .collect();
    let initials = match words.as_slice() {
        [] => "TIC".to_string(),
        [word] => word.chars().take(3).collect(),
        _ => words.iter().take(3).filter_map(|word| word.chars().next()).collect(),
    };
    Some(initials.to_uppercase().chars().take(3).collect())
}

#[cfg(test)]
mod tests {
    use super::tray_label;

    #[test]
    fn generic_build_never_inherits_a_company_label() {
        assert_eq!(tray_label("Tico", "", "ACME"), None);
    }

    #[test]
    fn company_labels_are_compact_and_unicode_safe() {
        for (name, expected) in [
            ("Acme Tico", "ACM"), ("Blue Harbor Tico", "BH"),
            ("Acme-North", "AN"), ("A B C D", "ABC"),
            ("Élan", "ÉLA"), ("東京商事", "東京商"), ("ßeta", "SSE"),
            ("Tico", "TIC"), ("---", "TIC"),
        ] {
            assert_eq!(tray_label(name, "company", "").as_deref(), Some(expected));
        }
    }

    #[test]
    fn private_override_distinguishes_collisions_without_changing_identity() {
        assert_eq!(tray_label("Acme", "acme-one", "a1").as_deref(), Some("A1"));
        assert_eq!(tray_label("Acme", "acme-two", "a2").as_deref(), Some("A2"));
    }
}
