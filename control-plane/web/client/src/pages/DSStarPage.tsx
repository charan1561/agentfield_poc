import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Upload,
  FileSpreadsheet,
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  Trash2,
  Microscope,
  ChevronDown,
  ChevronUp,
  Code2,
  FileText,
  BarChart3,
} from "lucide-react";
import { WorkflowDAGViewer } from "@/components/WorkflowDAG";
import { StepDetail } from "@/components/StepDetail";
import { getWorkflowDAGLightweight } from "@/services/workflowsApi";
import { dsStarApi } from "@/services/dsStarApi";
import type { AsyncExecuteResponse, ExecutionStatusResponse } from "@/types/execution";
import type { WorkflowDAGLightweightResponse } from "@/types/workflows";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type PipelinePhase = "idle" | "uploading" | "running" | "completed" | "error";

interface UploadedFile {
  name: string;
  size: number;
  status: "uploading" | "done" | "error";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function FileUploadZone({
  files,
  onFilesAdded,
  onRemove,
  disabled,
}: {
  files: UploadedFile[];
  onFilesAdded: (files: File[]) => void;
  onRemove: (name: string) => void;
  disabled: boolean;
}) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (disabled) return;
      const dropped = Array.from(e.dataTransfer.files).filter(
        (f) => f.name.endsWith(".csv") || f.name.endsWith(".xlsx") || f.name.endsWith(".json")
      );
      if (dropped.length > 0) onFilesAdded(dropped);
    },
    [onFilesAdded, disabled]
  );

  const handleSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = e.target.files ? Array.from(e.target.files) : [];
      if (selected.length > 0) onFilesAdded(selected);
      if (inputRef.current) inputRef.current.value = "";
    },
    [onFilesAdded]
  );

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        className={cn(
          "border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors",
          dragOver
            ? "border-primary bg-primary/5"
            : "border-border/60 hover:border-primary/40 hover:bg-muted/30",
          disabled && "opacity-50 cursor-not-allowed"
        )}
      >
        <Upload className="mx-auto h-8 w-8 text-muted-foreground mb-2" />
        <p className="text-sm font-medium text-foreground">
          Drop CSV, XLSX, or JSON files here
        </p>
        <p className="text-xs text-muted-foreground mt-1">
          or click to browse
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.xlsx,.json"
          multiple
          onChange={handleSelect}
          className="hidden"
          disabled={disabled}
        />
      </div>

      {files.length > 0 && (
        <div className="space-y-1.5">
          {files.map((f) => (
            <div
              key={f.name}
              className="flex items-center justify-between px-3 py-2 rounded-md bg-muted/40 border border-border/40"
            >
              <div className="flex items-center gap-2 min-w-0">
                <FileSpreadsheet className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="text-sm truncate">{f.name}</span>
                <span className="text-xs text-muted-foreground">
                  {formatBytes(f.size)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {f.status === "uploading" && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                )}
                {f.status === "done" && (
                  <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                )}
                {f.status === "error" && (
                  <XCircle className="h-3.5 w-3.5 text-destructive" />
                )}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onRemove(f.name);
                  }}
                  disabled={disabled || f.status === "uploading"}
                  className="text-muted-foreground hover:text-foreground disabled:opacity-30"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ResultsPanel({ result }: { result: ExecutionStatusResponse | null }) {
  const [codeOpen, setCodeOpen] = useState(false);

  if (!result?.result) return null;

  const data = result.result;
  const rawScore = typeof data.run_score === "object" && data.run_score !== null
    ? (data.run_score as Record<string, unknown>).score
    : data.run_score;
  const score = rawScore != null ? Number(rawScore) : NaN;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <Card variant="muted" interactive={false}>
          <CardContent className="p-4 text-center">
            <div className="text-2xl font-bold">
              {data.iterations ?? "-"}
            </div>
            <div className="text-xs text-muted-foreground mt-1">Iterations</div>
          </CardContent>
        </Card>
        <Card variant="muted" interactive={false}>
          <CardContent className="p-4 text-center">
            <div className={cn("text-2xl font-bold", data.verified ? "text-green-500" : "text-amber-500")}>
              {data.verified ? "Yes" : "No"}
            </div>
            <div className="text-xs text-muted-foreground mt-1">Verified</div>
          </CardContent>
        </Card>
        <Card variant="muted" interactive={false}>
          <CardContent className="p-4 text-center">
            <div className={cn(
              "text-2xl font-bold",
              !isNaN(score) && score >= 0.7 ? "text-green-500" : !isNaN(score) && score >= 0.4 ? "text-amber-500" : "text-destructive"
            )}>
              {!isNaN(score) ? score.toFixed(2) : "-"}
            </div>
            <div className="text-xs text-muted-foreground mt-1">Score</div>
          </CardContent>
        </Card>
      </div>

      {data.final_answer && (
        <Card variant="surface" interactive={false}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <FileText className="h-4 w-4" />
              Final Answer
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="prose prose-sm max-w-none prose-invert prose-headings:text-foreground prose-p:text-muted-foreground prose-strong:text-foreground prose-code:text-foreground prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  h1: ({ children }) => <h1 className="text-lg font-semibold mb-3 mt-4 first:mt-0 text-foreground border-b border-border pb-2">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-base font-semibold mb-2 mt-3 first:mt-0 text-foreground">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-sm font-medium mb-2 mt-2 text-foreground">{children}</h3>,
                  p: ({ children }) => <p className="mb-2 text-sm leading-relaxed text-muted-foreground">{children}</p>,
                  ul: ({ children }) => <ul className="list-disc list-inside mb-3 text-sm space-y-1">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal list-inside mb-3 text-sm space-y-1">{children}</ol>,
                  li: ({ children }) => <li className="leading-relaxed text-muted-foreground">{children}</li>,
                  strong: ({ children }) => <strong className="text-foreground font-semibold">{children}</strong>,
                  em: ({ children }) => <em className="text-muted-foreground">{children}</em>,
                  table: ({ children }) => (
                    <div className="overflow-auto mb-3 border border-border rounded-lg">
                      <table className="min-w-full text-sm">{children}</table>
                    </div>
                  ),
                  thead: ({ children }) => <thead className="bg-muted/50">{children}</thead>,
                  th: ({ children }) => (
                    <th className="border-b border-border px-3 py-2 text-left text-xs font-semibold text-foreground uppercase tracking-wider">
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td className="border-b border-border/50 px-3 py-2 text-sm text-muted-foreground">
                      {children}
                    </td>
                  ),
                  tr: ({ children }) => <tr className="hover:bg-muted/30 transition-colors">{children}</tr>,
                  blockquote: ({ children }) => (
                    <blockquote className="border-l-4 border-accent-primary pl-3 italic text-muted-foreground mb-2 bg-muted/30 py-1 rounded-r">
                      {children}
                    </blockquote>
                  ),
                  code: ({ children, className }) => {
                    const isBlock = className?.includes("language-");
                    return isBlock ? (
                      <code className={className}>{children}</code>
                    ) : (
                      <code className="bg-muted px-1.5 py-0.5 rounded text-xs font-mono text-foreground border border-border">
                        {children}
                      </code>
                    );
                  },
                  pre: ({ children }) => (
                    <pre className="bg-muted/50 border border-border rounded-lg p-3 text-xs overflow-x-auto mb-3 font-mono">
                      {children}
                    </pre>
                  ),
                  hr: () => <hr className="border-border my-4" />,
                }}
              >
                {data.final_answer}
              </ReactMarkdown>
            </div>
          </CardContent>
        </Card>
      )}

      {data.final_code && (
        <Card variant="surface" interactive={false}>
          <CardHeader className="pb-2">
            <button
              onClick={() => setCodeOpen(!codeOpen)}
              className="flex items-center gap-2 text-sm font-semibold w-full text-left"
            >
              <Code2 className="h-4 w-4" />
              Generated Code
              {codeOpen ? (
                <ChevronUp className="h-3.5 w-3.5 ml-auto" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5 ml-auto" />
              )}
            </button>
          </CardHeader>
          {codeOpen && (
            <CardContent>
              <pre className="text-xs bg-muted/50 border border-border rounded-lg p-4 overflow-x-auto max-h-96 font-mono leading-relaxed">
                <code>{data.final_code}</code>
              </pre>
            </CardContent>
          )}
        </Card>
      )}

      {data.plans && data.plans.length > 0 && (
        <Card variant="surface" interactive={false}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              Analysis Plan ({data.plans.length} steps)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="text-sm space-y-2 list-none">
              {data.plans.map((step: string, i: number) => (
                <li key={i} className="flex gap-3 text-muted-foreground">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-muted flex items-center justify-center text-xs font-semibold text-foreground">
                    {i + 1}
                  </span>
                  <span className="leading-relaxed pt-0.5">{step}</span>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export function DSStarPage() {
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [query, setQuery] = useState("");
  const [maxIterations, setMaxIterations] = useState(20);
  const [guidelines, setGuidelines] = useState("");
  const [phase, setPhase] = useState<PipelinePhase>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const [executionId, setExecutionId] = useState<string | null>(null);
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const readyFiles = files.filter((f) => f.status === "done").map((f) => f.name);
  const canExecute =
    phase !== "running" &&
    phase !== "uploading" &&
    readyFiles.length > 0 &&
    query.trim().length > 0;

  // Fetch uploaded files on mount
  useEffect(() => {
    dsStarApi.listFiles().then((remote) => {
      if (remote.length > 0) {
        setFiles((prev) => {
          const existing = new Set(prev.map((f) => f.name));
          const merged = [...prev];
          for (const rf of remote) {
            if (!existing.has(rf.name)) {
              merged.push({ name: rf.name, size: rf.size, status: "done" });
            }
          }
          return merged;
        });
      }
    });
  }, []);

  const handleFilesAdded = useCallback(async (newFiles: File[]) => {
    const entries: UploadedFile[] = newFiles.map((f) => ({
      name: f.name,
      size: f.size,
      status: "uploading" as const,
    }));
    setFiles((prev) => [...prev, ...entries]);
    setPhase("uploading");

    for (const file of newFiles) {
      try {
        await dsStarApi.uploadFile(file);
        setFiles((prev) =>
          prev.map((f) =>
            f.name === file.name ? { ...f, status: "done" as const } : f
          )
        );
      } catch {
        setFiles((prev) =>
          prev.map((f) =>
            f.name === file.name ? { ...f, status: "error" as const } : f
          )
        );
      }
    }
    setPhase("idle");
  }, []);

  const handleRemoveFile = useCallback((name: string) => {
    setFiles((prev) => prev.filter((f) => f.name !== name));
  }, []);

  const handleExecute = useCallback(async () => {
    if (!canExecute) return;
    setPhase("running");
    setErrorMsg(null);
    setExecutionId(null);
    setWorkflowId(null);
    setRunId(null);
    setSelectedStepId(null);

    try {
      const resp: AsyncExecuteResponse = await dsStarApi.executePipeline({
        query: query.trim(),
        data_files: readyFiles,
        max_iterations: maxIterations,
        guidelines: guidelines.trim() || undefined,
      });
      setExecutionId(resp.execution_id);
      setWorkflowId(resp.workflow_id);
      setRunId(resp.run_id ?? resp.workflow_id);
    } catch (err: any) {
      setPhase("error");
      setErrorMsg(err.message ?? "Failed to start pipeline");
    }
  }, [canExecute, query, readyFiles, maxIterations, guidelines]);

  // Poll execution status
  const { data: execStatus } = useQuery<ExecutionStatusResponse>({
    queryKey: ["ds-star-exec", executionId],
    queryFn: () => dsStarApi.getExecutionStatus(executionId!),
    enabled: !!executionId && phase === "running",
    refetchInterval: (q) => {
      const st = q.state.data?.status;
      if (st === "succeeded" || st === "failed" || st === "error") return false;
      return 2500;
    },
  });

  useEffect(() => {
    if (!execStatus) return;
    if (execStatus.status === "succeeded") {
      setPhase("completed");
    } else if (execStatus.status === "failed" || execStatus.status === "error") {
      setPhase("error");
      setErrorMsg(execStatus.error ?? "Pipeline failed");
    }
    if (execStatus.run_id && !runId) {
      setRunId(execStatus.run_id);
    }
  }, [execStatus, runId]);

  // Poll DAG
  const dagQueryId = runId ?? workflowId;
  const { data: dagData, isLoading: dagLoading } = useQuery<WorkflowDAGLightweightResponse>({
    queryKey: ["ds-star-dag", dagQueryId],
    queryFn: () => getWorkflowDAGLightweight(dagQueryId!),
    enabled: !!dagQueryId,
    refetchInterval: (q) => {
      const st = q.state.data?.workflow_status;
      if (st === "running" || st === "pending") return 2500;
      return false;
    },
  });

  const phaseLabel: Record<PipelinePhase, string> = {
    idle: "Ready",
    uploading: "Uploading...",
    running: "Running...",
    completed: "Completed",
    error: "Error",
  };

  return (
    <div className="-m-4 sm:-m-6 flex flex-col" style={{ height: "calc(100vh - 4rem)" }}>
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-border/60 shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center h-9 w-9 rounded-lg bg-primary/10">
            <Microscope className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">DS Star</h1>
            <p className="text-xs text-muted-foreground">
              Data Science Agent — Iterative Planning & Verification
            </p>
          </div>
        </div>
        <Badge
          variant={
            phase === "completed"
              ? "success"
              : phase === "error"
                ? "destructive"
                : phase === "running"
                  ? "default"
                  : "secondary"
          }
        >
          {phase === "running" && (
            <Loader2 className="h-3 w-3 animate-spin mr-1" />
          )}
          {phaseLabel[phase]}
        </Badge>
      </div>

      {/* Main content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        <div className="grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-0 h-full">
          {/* Left panel: config */}
          <div className="border-r border-border/60 overflow-y-auto p-5 space-y-5">
            {/* File Upload */}
            <Card variant="surface" interactive={false}>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Data Files</CardTitle>
              </CardHeader>
              <CardContent>
                <FileUploadZone
                  files={files}
                  onFilesAdded={handleFilesAdded}
                  onRemove={handleRemoveFile}
                  disabled={phase === "running"}
                />
              </CardContent>
            </Card>

            {/* Query */}
            <Card variant="surface" interactive={false}>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Query</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="e.g. Describe the key patterns in the data and create visualizations..."
                  disabled={phase === "running"}
                  rows={4}
                  className="w-full rounded-md border border-border/60 bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-y disabled:opacity-50"
                />

                <button
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
                >
                  Advanced options
                  {showAdvanced ? (
                    <ChevronUp className="h-3 w-3" />
                  ) : (
                    <ChevronDown className="h-3 w-3" />
                  )}
                </button>

                {showAdvanced && (
                  <div className="space-y-3 pt-1">
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">
                        Max Iterations
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={50}
                        value={maxIterations}
                        onChange={(e) =>
                          setMaxIterations(
                            Math.max(1, Math.min(50, parseInt(e.target.value) || 20))
                          )
                        }
                        disabled={phase === "running"}
                        className="w-full rounded-md border border-border/60 bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">
                        Guidelines (optional)
                      </label>
                      <textarea
                        value={guidelines}
                        onChange={(e) => setGuidelines(e.target.value)}
                        placeholder="Additional constraints or instructions..."
                        disabled={phase === "running"}
                        rows={2}
                        className="w-full rounded-md border border-border/60 bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-y disabled:opacity-50"
                      />
                    </div>
                  </div>
                )}

                <Button
                  onClick={handleExecute}
                  disabled={!canExecute}
                  className="w-full"
                  size="default"
                >
                  {phase === "running" ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin mr-2" />
                      Running Pipeline...
                    </>
                  ) : (
                    <>
                      <Play className="h-4 w-4 mr-2" />
                      Execute Pipeline
                    </>
                  )}
                </Button>

                {errorMsg && (
                  <div className="rounded-md bg-destructive/10 border border-destructive/30 p-3 text-sm text-destructive">
                    {errorMsg}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Results */}
            {phase === "completed" && execStatus && (
              <Card variant="surface" interactive={false}>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-500" />
                    Results
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <ResultsPanel result={execStatus} />
                </CardContent>
              </Card>
            )}
          </div>

          {/* Right panel: DAG + step detail */}
          <div className="flex flex-col overflow-hidden">
            {dagQueryId ? (
              <>
                <div className="flex-1 min-h-[400px]">
                  <WorkflowDAGViewer
                    workflowId={dagQueryId}
                    dagData={dagData}
                    loading={dagLoading}
                    onExecutionClick={(node) =>
                      setSelectedStepId(node.execution_id)
                    }
                    className="h-full"
                  />
                </div>

                {selectedStepId && (
                  <div className="border-t border-border/60 max-h-[45%] overflow-y-auto">
                    <div className="p-4">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-sm font-semibold">Step Detail</h3>
                        <button
                          onClick={() => setSelectedStepId(null)}
                          className="text-xs text-muted-foreground hover:text-foreground"
                        >
                          Close
                        </button>
                      </div>
                      <StepDetail executionId={selectedStepId} />
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="flex items-center justify-center min-h-[400px] h-full text-muted-foreground">
                <div className="text-center space-y-2">
                  <Microscope className="h-12 w-12 mx-auto opacity-20" />
                  <p className="text-sm">
                    Upload data files and run a query to see the workflow DAG
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
