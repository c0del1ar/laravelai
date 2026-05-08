package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	defaultOutputDir       = "/app/data/ytmp3"
	defaultCookies         = "/app/cookies/youtube.cookies.txt"
	youtubeExtractorArgs   = ""
	youtubeRemoteComponent = "ejs:github"
	maxStderrChars         = 4000
)

var youtubeURLRe = regexp.MustCompile(`(?i)^https?://(www\.)?(youtube\.com|youtu\.be|music\.youtube\.com)/.+`)
var bitrateRe = regexp.MustCompile(`\b(\d+(?:\.\d+)?)k\b`)
var ansiRe = regexp.MustCompile(`\x1b\[[0-9;]*[A-Za-z]`)

type toolPayload struct {
	Message string         `json:"message"`
	Files   []filePayload  `json:"files,omitempty"`
	Data    map[string]any `json:"data,omitempty"`
}

type filePayload struct {
	Path    string `json:"path"`
	Name    string `json:"name,omitempty"`
	MIME    string `json:"mime,omitempty"`
	Caption string `json:"caption,omitempty"`
	Variant string `json:"variant,omitempty"`
}

type ytdlpMetadata struct {
	Formats []ytdlpFormat `json:"formats"`
}

type ytdlpFormat struct {
	FormatID string  `json:"format_id"`
	Ext      string  `json:"ext"`
	VCodec   string  `json:"vcodec"`
	ACodec   string  `json:"acodec"`
	ABR      float64 `json:"abr"`
	TBR      float64 `json:"tbr"`
	ASR      int     `json:"asr"`
	Filesize int64   `json:"filesize"`
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err.Error())
		os.Exit(1)
	}
}

func run() error {
	if len(os.Args) < 2 {
		return errors.New("missing url")
	}

	rawURL := strings.TrimSpace(os.Args[1])
	if err := validateYouTubeURL(rawURL); err != nil {
		return err
	}

	outputDir := strings.TrimSpace(os.Getenv("YTMP3_OUTPUT_DIR"))
	if outputDir == "" {
		outputDir = defaultOutputDir
	}
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return fmt.Errorf("create output directory: %w", err)
	}

	cookiesFile := strings.TrimSpace(os.Getenv("YTMP3_COOKIES_FILE"))
	if cookiesFile == "" {
		cookiesFile = defaultCookies
	}
	activeCookiesFile := ""
	cleanupCookies := func() {}
	if fileExists(cookiesFile) {
		prepared, cleanup, err := prepareCookiesFile(cookiesFile)
		if err != nil {
			return fmt.Errorf("prepare YouTube cookies: %w", err)
		}
		activeCookiesFile = prepared
		cleanupCookies = cleanup
	}
	defer cleanupCookies()

	formatID, err := bestAudioFormat(rawURL, activeCookiesFile, cookiesFile)
	if err != nil {
		return err
	}

	outputTemplate := filepath.Join(outputDir, "%(title).180B [%(id)s].%(ext)s")
	baseArgs := []string{"yt-dlp"}
	baseArgs = appendYTDLPExtractorArgs(baseArgs)
	baseArgs = append(baseArgs,
		"--remote-components", youtubeRemoteComponent,
		"--no-playlist",
		"--format", formatID,
		"--extract-audio",
		"--audio-format", "mp3",
		"--audio-quality", "0",
		"--max-filesize", "100M",
		"--paths", outputDir,
		"--output", outputTemplate,
		"--print", "after_move:filepath",
		"--no-warnings",
	)
	if activeCookiesFile != "" {
		baseArgs = append(baseArgs, "--cookies", activeCookiesFile)
	}
	baseArgs = append(baseArgs, rawURL)

	stdout, stderr, err := runYTDLP(baseArgs)
	if err != nil && isUnavailableFormat(stderr) {
		fallbackArgs := replaceFormat(baseArgs, "bestaudio/best")
		stdout, stderr, err = runYTDLP(fallbackArgs)
	}
	if err != nil {
		detail := truncate(stderr, maxStderrChars)
		if strings.Contains(strings.ToLower(detail), "sign in to confirm") {
			return fmt.Errorf("yt-dlp needs YouTube cookies. Export cookies to %s, then recreate cli_tool_runner. Detail: %w: %s", cookiesFile, err, detail)
		}
		return fmt.Errorf("yt-dlp failed: %w: %s", err, detail)
	}

	filePath := lastNonEmptyLine(stdout)
	if filePath == "" {
		return errors.New("yt-dlp did not return an output file path")
	}
	if !filepath.IsAbs(filePath) {
		filePath = filepath.Join(outputDir, filePath)
	}

	info, err := os.Stat(filePath)
	if err != nil {
		return fmt.Errorf("output file not found: %w", err)
	}

	files := []filePayload{
		{
			Path:    filePath,
			Name:    filepath.Base(filePath),
			MIME:    "audio/mpeg",
			Caption: "YouTube MP3",
			Variant: "download",
		},
	}
	whatsappPath, whatsappErr := createWhatsAppVoice(filePath)
	if whatsappErr == nil {
		files = append(files, filePayload{
			Path:    whatsappPath,
			Name:    filepath.Base(whatsappPath),
			MIME:    "audio/ogg",
			Caption: "WhatsApp voice note",
			Variant: "whatsapp_voice",
		})
	}

	data := map[string]any{
		"url":          rawURL,
		"format_id":    formatID,
		"size_bytes":   info.Size(),
		"cookies_used": activeCookiesFile != "",
		"generated_at": time.Now().Format(time.RFC3339),
	}
	if whatsappErr != nil {
		data["whatsapp_voice_error"] = whatsappErr.Error()
	}

	payload := toolPayload{
		Message: fmt.Sprintf("Audio selesai diproses: %s", filepath.Base(filePath)),
		Files:   files,
		Data:    data,
	}

	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)
	return enc.Encode(payload)
}

func bestAudioFormat(rawURL string, cookiesFile string, originalCookiesFile string) (string, error) {
	formatID, listErr := bestAudioFormatFromList(rawURL, cookiesFile, originalCookiesFile)
	if listErr == nil {
		return formatID, nil
	}

	args := []string{"yt-dlp"}
	args = appendYTDLPExtractorArgs(args)
	args = append(args,
		"--ignore-config",
		"--remote-components", youtubeRemoteComponent,
		"--no-playlist",
		"--dump-single-json",
		"--no-warnings",
	)
	if cookiesFile != "" {
		args = append(args, "--cookies", cookiesFile)
	}
	args = append(args, rawURL)

	stdout, stderr, err := runYTDLP(args)
	if err != nil {
		detail := truncate(stderr, maxStderrChars)
		if strings.Contains(strings.ToLower(detail), "sign in to confirm") {
			return "", fmt.Errorf("yt-dlp needs valid YouTube cookies. Export cookies to %s, then recreate cli_tool_runner. Detail: %w: %s", originalCookiesFile, err, detail)
		}
		return "", fmt.Errorf("yt-dlp list-formats failed and metadata fallback failed: list=%w metadata=%w: %s", listErr, err, detail)
	}

	var metadata ytdlpMetadata
	if err := json.Unmarshal([]byte(stdout), &metadata); err != nil {
		return "", fmt.Errorf("parse yt-dlp metadata: %w", err)
	}

	candidates := make([]ytdlpFormat, 0)
	for _, format := range metadata.Formats {
		if format.FormatID == "" {
			continue
		}
		if strings.EqualFold(format.ACodec, "none") || strings.TrimSpace(format.ACodec) == "" {
			continue
		}
		if !strings.EqualFold(format.VCodec, "none") {
			continue
		}
		candidates = append(candidates, format)
	}
	if len(candidates) == 0 {
		return "", errors.New("no audio-only format found")
	}

	sort.SliceStable(candidates, func(i, j int) bool {
		return audioScore(candidates[i]) > audioScore(candidates[j])
	})
	return candidates[0].FormatID, nil
}

func bestAudioFormatFromList(rawURL string, cookiesFile string, originalCookiesFile string) (string, error) {
	args := []string{"yt-dlp"}
	args = appendYTDLPExtractorArgs(args)
	args = append(args,
		"--ignore-config",
		"--remote-components", youtubeRemoteComponent,
		"--no-playlist",
		"--list-formats",
		"--no-warnings",
	)
	if cookiesFile != "" {
		args = append(args, "--cookies", cookiesFile)
	}
	args = append(args, rawURL)

	stdout, stderr, err := runYTDLP(args)
	candidates := make([]ytdlpFormat, 0)
	listOutput := stdout
	if strings.TrimSpace(stderr) != "" {
		listOutput = listOutput + "\n" + stderr
	}
	for _, line := range strings.Split(listOutput, "\n") {
		format, ok := parseListFormatLine(line)
		if ok {
			candidates = append(candidates, format)
		}
	}
	if len(candidates) > 0 {
		sort.SliceStable(candidates, func(i, j int) bool {
			return audioScore(candidates[i]) > audioScore(candidates[j])
		})
		return candidates[0].FormatID, nil
	}

	if err != nil {
		detail := truncate(listOutput, maxStderrChars)
		if strings.Contains(strings.ToLower(detail), "sign in to confirm") {
			return "", fmt.Errorf("yt-dlp needs valid YouTube cookies. Export cookies to %s, then recreate cli_tool_runner. Detail: %w: %s", originalCookiesFile, err, detail)
		}
		return "", fmt.Errorf("yt-dlp list-formats failed: %w: %s", err, detail)
	}

	if len(candidates) == 0 {
		return "", fmt.Errorf("no audio-only format found from list-formats. output=%s", truncate(listOutput, maxStderrChars))
	}
	return "", errors.New("no audio-only format found from list-formats")
}

func parseListFormatLine(line string) (ytdlpFormat, bool) {
	line = strings.TrimSpace(ansiRe.ReplaceAllString(line, ""))
	if line == "" || strings.HasPrefix(line, "[") || strings.HasPrefix(line, "ID ") || strings.HasPrefix(line, "─") {
		return ytdlpFormat{}, false
	}
	fields := strings.Fields(line)
	if len(fields) < 3 {
		return ytdlpFormat{}, false
	}
	if !strings.Contains(strings.ToLower(line), "audio only") {
		return ytdlpFormat{}, false
	}

	format := ytdlpFormat{
		FormatID: fields[0],
		Ext:      fields[1],
		VCodec:   "none",
	}
	for _, match := range bitrateRe.FindAllStringSubmatch(line, -1) {
		if len(match) < 2 {
			continue
		}
		value, err := strconv.ParseFloat(match[1], 64)
		if err == nil && value > format.ABR {
			format.ABR = value
		}
	}
	return format, true
}

func audioScore(format ytdlpFormat) float64 {
	score := format.ABR
	if score <= 0 {
		score = format.TBR
	}
	if strings.EqualFold(format.Ext, "m4a") {
		score += 5
	}
	if format.ASR >= 44100 {
		score += 2
	}
	return score
}

func runYTDLP(args []string) (string, string, error) {
	cmd := exec.Command(args[0], args[1:]...)

	var stdout bytes.Buffer
	var stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	if err := cmd.Run(); err != nil {
		return stdout.String(), stderr.String(), err
	}
	return stdout.String(), stderr.String(), nil
}

func createWhatsAppVoice(inputPath string) (string, error) {
	if strings.TrimSpace(inputPath) == "" {
		return "", errors.New("missing input file")
	}
	ext := filepath.Ext(inputPath)
	base := strings.TrimSuffix(inputPath, ext)
	outputPath := base + ".whatsapp.ogg"
	args := []string{
		"-y",
		"-i", inputPath,
		"-vn",
		"-c:a", "libopus",
		"-b:a", "64k",
		"-ar", "48000",
		"-ac", "1",
		"-f", "ogg",
		outputPath,
	}
	cmd := exec.Command("ffmpeg", args...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("ffmpeg whatsapp voice conversion failed: %w: %s", err, truncate(stderr.String(), maxStderrChars))
	}
	return outputPath, nil
}

func appendYTDLPExtractorArgs(args []string) []string {
	if strings.TrimSpace(youtubeExtractorArgs) == "" {
		return args
	}
	return append(args, "--extractor-args", youtubeExtractorArgs)
}

func isUnavailableFormat(stderr string) bool {
	return strings.Contains(strings.ToLower(stderr), "requested format is not available")
}

func replaceFormat(args []string, value string) []string {
	out := append([]string(nil), args...)
	for i := 0; i < len(out)-1; i++ {
		if out[i] == "--format" {
			out[i+1] = value
			return out
		}
	}
	return append([]string{"yt-dlp", "--format", value}, out[1:]...)
}

func validateYouTubeURL(raw string) error {
	if !youtubeURLRe.MatchString(raw) {
		return errors.New("url must be a YouTube URL")
	}
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return errors.New("invalid url")
	}
	return nil
}

func lastNonEmptyLine(value string) string {
	lines := strings.Split(value, "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		line := strings.TrimSpace(lines[i])
		if line != "" {
			return line
		}
	}
	return ""
}

func fileExists(path string) bool {
	if strings.TrimSpace(path) == "" {
		return false
	}
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func prepareCookiesFile(path string) (string, func(), error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", func() {}, err
	}

	normalized, valid := normalizeCookies(string(raw))
	if valid == 0 {
		return "", func() {}, fmt.Errorf("cookie file has no valid Netscape entries: %s", path)
	}

	tmp, err := os.CreateTemp("", "ytmp3-cookies-*.txt")
	if err != nil {
		return "", func() {}, err
	}
	cleanup := func() {
		_ = os.Remove(tmp.Name())
	}

	if _, err := tmp.WriteString(normalized); err != nil {
		_ = tmp.Close()
		cleanup()
		return "", func() {}, err
	}
	if err := tmp.Close(); err != nil {
		cleanup()
		return "", func() {}, err
	}

	return tmp.Name(), cleanup, nil
}

func normalizeCookies(raw string) (string, int) {
	lines := []string{"# Netscape HTTP Cookie File"}
	valid := 0
	for _, line := range strings.Split(raw, "\n") {
		normalized, ok := normalizeCookieLine(line)
		if !ok {
			continue
		}
		lines = append(lines, normalized)
		valid++
	}
	return strings.Join(lines, "\n") + "\n", valid
}

func normalizeCookieLine(line string) (string, bool) {
	line = strings.TrimSpace(line)
	if line == "" || (strings.HasPrefix(line, "#") && !strings.HasPrefix(line, "#HttpOnly_")) {
		return "", false
	}

	if strings.Count(line, "\t") >= 6 {
		fields := strings.Split(line, "\t")
		if len(fields) >= 7 {
			return strings.Join(fields[:6], "\t") + "\t" + strings.Join(fields[6:], "\t"), true
		}
		return "", false
	}

	fields := strings.Fields(line)
	if len(fields) < 7 {
		return "", false
	}
	return strings.Join(fields[:6], "\t") + "\t" + strings.Join(fields[6:], ""), true
}

func truncate(value string, max int) string {
	value = strings.TrimSpace(value)
	if len(value) <= max {
		return value
	}
	return value[:max] + "..."
}
