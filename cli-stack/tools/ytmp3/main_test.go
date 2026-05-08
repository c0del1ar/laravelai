package main

import "testing"

func TestParseListFormatLineAudio(t *testing.T) {
	format, ok := parseListFormatLine("251 webm  audio only      2 │    2.31MiB  151k https │ audio only          opus       151k 48k [pt] medium, webm_dash")
	if !ok {
		t.Fatal("expected audio format")
	}
	if format.FormatID != "251" {
		t.Fatalf("format id = %q, want 251", format.FormatID)
	}
	if format.ABR != 151 {
		t.Fatalf("abr = %v, want 151", format.ABR)
	}
}

func TestParseListFormatLineVideoIgnored(t *testing.T) {
	_, ok := parseListFormatLine("137 mp4   1920x1080   24    │   35.07MiB 2304k https │ avc1.640028   2304k video only          1080p, mp4_dash")
	if ok {
		t.Fatal("expected video-only format to be ignored")
	}
}

func TestNormalizeCookieLineSpaceSeparated(t *testing.T) {
	line := ".youtube.com TRUE / TRUE 1793728763 VISITOR_INFO1_LIVE rNB51P3_4vA"
	got, ok := normalizeCookieLine(line)
	if !ok {
		t.Fatal("expected cookie line to normalize")
	}
	want := ".youtube.com\tTRUE\t/\tTRUE\t1793728763\tVISITOR_INFO1_LIVE\trNB51P3_4vA"
	if got != want {
		t.Fatalf("normalized cookie = %q, want %q", got, want)
	}
}

func TestNormalizeCookieLineTabSeparated(t *testing.T) {
	line := ".youtube.com\tTRUE\t/\tTRUE\t1793728763\tVISITOR_INFO1_LIVE\trNB51P3_4vA"
	got, ok := normalizeCookieLine(line)
	if !ok {
		t.Fatal("expected cookie line to stay valid")
	}
	if got != line {
		t.Fatalf("normalized cookie = %q, want %q", got, line)
	}
}

func TestNormalizeCookieLineHttpOnly(t *testing.T) {
	line := "#HttpOnly_.youtube.com TRUE / TRUE 1812736772 SID token"
	got, ok := normalizeCookieLine(line)
	if !ok {
		t.Fatal("expected HttpOnly cookie line to normalize")
	}
	want := "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1812736772\tSID\ttoken"
	if got != want {
		t.Fatalf("normalized cookie = %q, want %q", got, want)
	}
}

func TestNormalizeCookiesCountsValidEntries(t *testing.T) {
	raw := "# Netscape HTTP Cookie File\ninvalid\n.youtube.com TRUE / TRUE 1793728763 GPS 1\n"
	normalized, valid := normalizeCookies(raw)
	if valid != 1 {
		t.Fatalf("valid = %d, want 1", valid)
	}
	if normalized != "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t1793728763\tGPS\t1\n" {
		t.Fatalf("normalized cookies = %q", normalized)
	}
}
