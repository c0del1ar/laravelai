package main

import (
	"bytes"
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

const (
	defaultAddr           = ":37000"
	defaultConfigPath     = "config/tools.json"
	defaultTimeoutSeconds = 45
	defaultMaxOutputBytes = 1024 * 1024
)

var slugRe = regexp.MustCompile(`^[a-z0-9][a-z0-9_-]{0,63}$`)

type Config struct {
	Tools map[string]ToolConfig `json:"tools"`
}

type ToolConfig struct {
	Name             string            `json:"name"`
	Description      string            `json:"description"`
	Command          string            `json:"command"`
	Args             []string          `json:"args"`
	Required         []string          `json:"required"`
	Patterns         map[string]string `json:"patterns"`
	Env              map[string]string `json:"env"`
	WorkingDir       string            `json:"working_dir"`
	TimeoutSeconds   int               `json:"timeout_seconds"`
	MaxOutputBytes   int               `json:"max_output_bytes"`
	OutputJSON       bool              `json:"output_json"`
	AllowStderrReply bool              `json:"allow_stderr_reply"`
}

type Server struct {
	cfg        Config
	apiKey     string
	baseDir    string
	configPath string
	logger     *slog.Logger
}

type RunRequest struct {
	Tool      string            `json:"tool"`
	Args      map[string]string `json:"args"`
	RequestID string            `json:"request_id"`
}

type RunResponse struct {
	OK         bool           `json:"ok"`
	Tool       string         `json:"tool"`
	RequestID  string         `json:"request_id,omitempty"`
	DurationMS int64          `json:"duration_ms"`
	ExitCode   int            `json:"exit_code"`
	Message    string         `json:"message,omitempty"`
	Stdout     string         `json:"stdout,omitempty"`
	Stderr     string         `json:"stderr,omitempty"`
	Files      []FileResponse `json:"files,omitempty"`
	Data       any            `json:"data,omitempty"`
	Truncated  bool           `json:"truncated,omitempty"`
	Error      string         `json:"error,omitempty"`
	Timeout    bool           `json:"timeout,omitempty"`
	UnauthDev  bool           `json:"unauthenticated_dev_mode,omitempty"`
}

type FileResponse struct {
	Path    string `json:"path"`
	Name    string `json:"name,omitempty"`
	MIME    string `json:"mime,omitempty"`
	Caption string `json:"caption,omitempty"`
}

type ToolPayload struct {
	Message string         `json:"message"`
	Files   []FileResponse `json:"files"`
	Data    any            `json:"data"`
}

type ToolListItem struct {
	Slug        string   `json:"slug"`
	Name        string   `json:"name"`
	Description string   `json:"description"`
	Required    []string `json:"required"`
}

type limitedBuffer struct {
	buf       bytes.Buffer
	limit     int
	truncated bool
}

func (b *limitedBuffer) Write(p []byte) (int, error) {
	if b.limit <= 0 {
		b.truncated = true
		return len(p), nil
	}
	remaining := b.limit - b.buf.Len()
	if remaining <= 0 {
		b.truncated = true
		return len(p), nil
	}
	if len(p) > remaining {
		b.buf.Write(p[:remaining])
		b.truncated = true
		return len(p), nil
	}
	b.buf.Write(p)
	return len(p), nil
}

func (b *limitedBuffer) String() string {
	return b.buf.String()
}

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	baseDir := env("CLI_TOOL_RUNNER_BASE_DIR", ".")
	absBaseDir, err := filepath.Abs(baseDir)
	if err != nil {
		fatal(logger, "resolve base dir", err)
	}

	configPath := env("CLI_TOOL_RUNNER_CONFIG", defaultConfigPath)
	if !filepath.IsAbs(configPath) {
		configPath = filepath.Join(absBaseDir, configPath)
	}

	cfg, err := loadConfig(configPath)
	if err != nil {
		fatal(logger, "load config", err)
	}
	if err := validateConfig(cfg); err != nil {
		fatal(logger, "validate config", err)
	}

	server := &Server{
		cfg:        cfg,
		apiKey:     os.Getenv("CLI_TOOL_RUNNER_KEY"),
		baseDir:    absBaseDir,
		configPath: configPath,
		logger:     logger,
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", server.handleHealth)
	mux.HandleFunc("GET /tools", server.handleTools)
	mux.HandleFunc("POST /run", server.handleRun)

	addr := env("CLI_TOOL_RUNNER_ADDR", defaultAddr)
	logger.Info("tool runner listening", "addr", addr, "config", configPath, "base_dir", absBaseDir)
	if server.apiKey == "" {
		logger.Warn("CLI_TOOL_RUNNER_KEY is empty; HTTP API is running in dev mode without auth")
	}

	httpServer := &http.Server{
		Addr:              addr,
		Handler:           requestLogMiddleware(logger, mux),
		ReadHeaderTimeout: 5 * time.Second,
	}
	if err := httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		fatal(logger, "listen", err)
	}
}

func loadConfig(path string) (Config, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return Config{}, err
	}
	var cfg Config
	if err := json.Unmarshal(raw, &cfg); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func validateConfig(cfg Config) error {
	if len(cfg.Tools) == 0 {
		return errors.New("config has no tools")
	}
	for slug, tool := range cfg.Tools {
		if !slugRe.MatchString(slug) {
			return fmt.Errorf("invalid tool slug %q", slug)
		}
		if strings.TrimSpace(tool.Command) == "" {
			return fmt.Errorf("tool %q has empty command", slug)
		}
		for name, pattern := range tool.Patterns {
			if strings.TrimSpace(name) == "" {
				return fmt.Errorf("tool %q has empty pattern name", slug)
			}
			if _, err := regexp.Compile(pattern); err != nil {
				return fmt.Errorf("tool %q pattern %q is invalid: %w", slug, name, err)
			}
		}
	}
	return nil
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"ok":      true,
		"service": "cli-tool-runner",
		"tools":   len(s.cfg.Tools),
	})
}

func (s *Server) handleTools(w http.ResponseWriter, r *http.Request) {
	if !s.authorized(r) {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}

	items := make([]ToolListItem, 0, len(s.cfg.Tools))
	for slug, tool := range s.cfg.Tools {
		items = append(items, ToolListItem{
			Slug:        slug,
			Name:        fallback(tool.Name, slug),
			Description: tool.Description,
			Required:    append([]string(nil), tool.Required...),
		})
	}
	sort.Slice(items, func(i, j int) bool { return items[i].Slug < items[j].Slug })
	writeJSON(w, http.StatusOK, map[string]any{"items": items})
}

func (s *Server) handleRun(w http.ResponseWriter, r *http.Request) {
	if !s.authorized(r) {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}

	var req RunRequest
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 64*1024)).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}

	req.Tool = strings.ToLower(strings.TrimSpace(req.Tool))
	if !slugRe.MatchString(req.Tool) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid tool"})
		return
	}

	tool, ok := s.cfg.Tools[req.Tool]
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "unknown tool"})
		return
	}

	response, status := s.runTool(r.Context(), req, tool)
	writeJSON(w, status, response)
}

func (s *Server) runTool(parent context.Context, req RunRequest, tool ToolConfig) (RunResponse, int) {
	start := time.Now()
	timeout := tool.TimeoutSeconds
	if timeout <= 0 {
		timeout = defaultTimeoutSeconds
	}
	outputLimit := tool.MaxOutputBytes
	if outputLimit <= 0 {
		outputLimit = defaultMaxOutputBytes
	}

	args, err := renderArgs(tool, req.Args)
	if err != nil {
		return RunResponse{OK: false, Tool: req.Tool, RequestID: req.RequestID, Error: err.Error()}, http.StatusBadRequest
	}

	workDir, command, err := s.resolveExecutionPaths(tool)
	if err != nil {
		return RunResponse{OK: false, Tool: req.Tool, RequestID: req.RequestID, Error: err.Error()}, http.StatusInternalServerError
	}

	ctx, cancel := context.WithTimeout(parent, time.Duration(timeout)*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, command, args...)
	cmd.Dir = workDir
	cmd.Env = os.Environ()
	for key, value := range tool.Env {
		cmd.Env = append(cmd.Env, fmt.Sprintf("%s=%s", key, value))
	}

	var stdout limitedBuffer
	var stderr limitedBuffer
	stdout.limit = outputLimit
	stderr.limit = outputLimit / 4
	if stderr.limit < 4096 {
		stderr.limit = 4096
	}
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err = cmd.Run()
	duration := time.Since(start).Milliseconds()
	response := RunResponse{
		OK:         err == nil,
		Tool:       req.Tool,
		RequestID:  req.RequestID,
		DurationMS: duration,
		ExitCode:   exitCode(err),
		Stdout:     strings.TrimSpace(stdout.String()),
		Truncated:  stdout.truncated || stderr.truncated,
	}
	if tool.AllowStderrReply || err != nil {
		response.Stderr = strings.TrimSpace(stderr.String())
	}

	if ctx.Err() == context.DeadlineExceeded {
		response.OK = false
		response.Timeout = true
		response.Error = "tool timeout"
		return response, http.StatusGatewayTimeout
	}
	if err != nil {
		response.Error = "tool failed"
		return response, http.StatusBadGateway
	}

	if tool.OutputJSON {
		var payload ToolPayload
		if parseErr := json.Unmarshal([]byte(response.Stdout), &payload); parseErr != nil {
			response.OK = false
			response.Error = "tool returned invalid json"
			return response, http.StatusBadGateway
		}
		response.Message = payload.Message
		response.Files = payload.Files
		response.Data = payload.Data
		response.Stdout = ""
		return response, http.StatusOK
	}

	response.Message = response.Stdout
	return response, http.StatusOK
}

func renderArgs(tool ToolConfig, values map[string]string) ([]string, error) {
	if values == nil {
		values = map[string]string{}
	}
	for _, name := range tool.Required {
		if strings.TrimSpace(values[name]) == "" {
			return nil, fmt.Errorf("missing required arg %q", name)
		}
	}
	for name, pattern := range tool.Patterns {
		value := values[name]
		if value == "" {
			continue
		}
		re, err := regexp.Compile(pattern)
		if err != nil {
			return nil, fmt.Errorf("invalid pattern for %q", name)
		}
		if !re.MatchString(value) {
			return nil, fmt.Errorf("arg %q does not match allowed pattern", name)
		}
	}

	args := make([]string, 0, len(tool.Args))
	for _, arg := range tool.Args {
		rendered, err := renderTemplateArg(arg, values)
		if err != nil {
			return nil, err
		}
		args = append(args, rendered)
	}
	return args, nil
}

func renderTemplateArg(template string, values map[string]string) (string, error) {
	result := template
	matches := regexp.MustCompile(`\{\{([a-zA-Z0-9_]+)\}\}`).FindAllStringSubmatch(template, -1)
	for _, match := range matches {
		key := match[1]
		value, ok := values[key]
		if !ok {
			return "", fmt.Errorf("missing arg %q", key)
		}
		result = strings.ReplaceAll(result, match[0], value)
	}
	return result, nil
}

func (s *Server) resolveExecutionPaths(tool ToolConfig) (string, string, error) {
	workDir := strings.TrimSpace(tool.WorkingDir)
	if workDir == "" {
		workDir = s.baseDir
	} else if !filepath.IsAbs(workDir) {
		workDir = filepath.Join(s.baseDir, workDir)
	}
	workDir = filepath.Clean(workDir)

	command := strings.TrimSpace(tool.Command)
	if strings.ContainsRune(command, os.PathSeparator) {
		if !filepath.IsAbs(command) {
			command = filepath.Join(s.baseDir, command)
		}
		command = filepath.Clean(command)
	}
	return workDir, command, nil
}

func (s *Server) authorized(r *http.Request) bool {
	if s.apiKey == "" {
		return true
	}
	provided := strings.TrimSpace(r.Header.Get("X-Tool-Runner-Key"))
	if provided == "" {
		provided = strings.TrimPrefix(strings.TrimSpace(r.Header.Get("Authorization")), "Bearer ")
	}
	return subtle.ConstantTimeCompare([]byte(provided), []byte(s.apiKey)) == 1
}

func exitCode(err error) int {
	if err == nil {
		return 0
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return exitErr.ExitCode()
	}
	return -1
}

func requestLogMiddleware(logger *slog.Logger, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		logger.Info("request", "method", r.Method, "path", r.URL.Path, "duration_ms", time.Since(start).Milliseconds())
	})
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func fallback(value string, fallbackValue string) string {
	if strings.TrimSpace(value) == "" {
		return fallbackValue
	}
	return value
}

func env(key string, fallbackValue string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallbackValue
	}
	return value
}

func fatal(logger *slog.Logger, msg string, err error) {
	logger.Error(msg, "error", err)
	os.Exit(1)
}
