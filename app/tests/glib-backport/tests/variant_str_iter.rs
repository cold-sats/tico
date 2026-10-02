//! Exercise the real GLib variadic output argument with optimization enabled.
//! The pre-backport implementation writes through an immutable reference;
//! Rust may discard that write and CStr::from_ptr then dereferences NULL.
use glib::variant::ToVariant;

const VALUES: [&str; 5] = ["", "alpha", "caf\u{e9}", "\u{6771}\u{4eac}", "omega"];

#[test]
fn forward_and_reverse_iteration_borrow_the_original_strings() {
    let variant = VALUES.to_variant();
    assert_eq!(variant.array_iter_str().unwrap().collect::<Vec<_>>(), VALUES);
    assert_eq!(variant.array_iter_str().unwrap().rev().collect::<Vec<_>>(),
               VALUES.into_iter().rev().collect::<Vec<_>>());
}

#[test]
fn nth_and_last_use_valid_written_output_pointers() {
    let variant = VALUES.to_variant();
    let mut iter = variant.array_iter_str().unwrap();
    assert_eq!(iter.nth(1), Some("alpha"));
    assert_eq!(iter.nth(1), Some("\u{6771}\u{4eac}"));
    assert_eq!(iter.last(), Some("omega"));
    assert_eq!(variant.array_iter_str().unwrap().last(), Some("omega"));
}

#[test]
fn nth_back_and_mixed_ends_keep_the_remaining_bounds() {
    let variant = VALUES.to_variant();
    let mut iter = variant.array_iter_str().unwrap();
    assert_eq!(iter.nth_back(1), Some("\u{6771}\u{4eac}"));
    assert_eq!(iter.next(), Some(""));
    assert_eq!(iter.len(), 2);
    assert_eq!(iter.next_back(), Some("caf\u{e9}"));
    assert_eq!(iter.next(), Some("alpha"));
    assert_eq!(iter.next(), None);
    assert_eq!(iter.next_back(), None);
}

#[test]
fn empty_single_and_overflowing_skips_are_fused() {
    let empty: [&str; 0] = [];
    let variant = empty.to_variant();
    assert_eq!(variant.array_iter_str().unwrap().next(), None);
    assert_eq!(variant.array_iter_str().unwrap().next_back(), None);
    assert_eq!(variant.array_iter_str().unwrap().last(), None);
    let variant = ["only"].to_variant();
    assert_eq!(variant.array_iter_str().unwrap().next_back(), Some("only"));
    let mut iter = variant.array_iter_str().unwrap();
    assert_eq!(iter.nth(usize::MAX), None);
    assert_eq!(iter.next_back(), None);
    let mut iter = variant.array_iter_str().unwrap();
    assert_eq!(iter.nth_back(usize::MAX), None);
    assert_eq!(iter.next(), None);
}

#[test]
fn borrowed_strings_stay_valid_after_the_iterator_is_dropped() {
    let variant = VALUES.to_variant();
    let strings = {
        let mut iter = variant.array_iter_str().unwrap();
        [iter.next().unwrap(), iter.nth(1).unwrap(), iter.next_back().unwrap()]
    };
    assert_eq!(strings, ["", "caf\u{e9}", "omega"]);
}
