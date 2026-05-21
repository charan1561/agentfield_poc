from typing import List, Dict, Any, Optional


# Appendix G.1 — Analyzer agent
def render_analyzer_prompt(filename: str) -> List[Dict[str, Any]]:
    """
    Returns messages for AnalyzerAgent to generate a single-file Python script that loads and describes the file.
    """
    user = f"""You are an expert data analyst.
Generate a Python code that loads and describes the content of {filename}.
# Requirement
The file can be unstructured or structured data.
If there are too many structured data, print out just a few examples.
Print out essential information. For example, print out all the column names.
The Python code should print out the content of {filename}.
The code should be a single-file Python program that is self-contained and can be executed as-is.
Your response should only contain a single code block.
Important: You should not include dummy contents since we will debug if error occurs.
Do not use try: and except: to prevent error. I will debug it later.
All files/documents are in `data/` directory."""
    return [{"role": "user", "content": user}]


# Appendix G.2 — Planner agent (initial)
def render_planner_init_prompt(question: str, file_summaries: List[str], filenames: List[str], guidelines: str, strategies: str = "") -> List[Dict[str, Any]]:
    """
    Generate messages for initial plan p0 using query and data descriptions.
    """
    given_data_blocks = []
    for fn, summ in zip(filenames, file_summaries):
        given_data_blocks.append(f"{fn}\n{summ}")
    given_data = "\n".join(given_data_blocks)

    context_block = f"\n# Context from past runs\n{strategies}\n" if strategies else ""

    user = f"""You are an expert data analyst.
In order to answer factoid questions based on the given data, you have to first plan effectively.
# Question
{question}
# Given data:
{given_data}
# Guidelines
{guidelines}{context_block}
# Your task
Suggest your very first step to answer the question above.
Your first step does not need to be sufficient to answer the question.
Just propose a very simple initial step, which can act as a good starting point to answer the question.
Your response should only contain an initial step."""
    return [{"role": "user", "content": user}]


# Appendix G.2 — Planner agent (next steps)
def render_planner_next_prompt(
    question: str,
    file_summaries: List[str],
    filenames: List[str],
    current_plans: List[str],
    last_result: str,
    guidelines: str,
    strategies: str = "",
) -> List[Dict[str, Any]]:
    """
    Generate messages for next plan pk+1 conditioned on current plans and latest execution result r_k.
    """
    _ = file_summaries, filenames, guidelines  # Available if needed

    plans_str = "\n".join([f"{i+1}. {step}" for i, step in enumerate(current_plans)])
    current_step = current_plans[-1] if current_plans else ""
    result_preview = last_result[:1500] if last_result else "(empty)"
    context_block = f"\n# Context from past runs\n{strategies}\n" if strategies else ""

    user = f"""You are an expert data analyst.
In order to answer factoid questions based on the given data, you have to first plan effectively.
Your task is to suggest next plan to do to answer the question.
# Question
{question}
# Current plans
{plans_str}
# Current step
{current_step}
# Obtained results from the current plans:
{result_preview}{context_block}
# Your task
Suggest your next step to answer the question above.
Your next step does not need to be sufficient to answer the question, but if it requires only final simple last step you may suggest it.
Just propose a very simple next step, which can act as a good intermediate point to answer the question.
Of course your response can be a plan which could directly answer the question.
Your response should only contain a next step without any explanation."""
    return [{"role": "user", "content": user}]


# Appendix G.3 — Coder agent (initial)
def render_coder_init_prompt(file_summaries: List[str], filenames: List[str], plan: str, strategies: str = "") -> List[Dict[str, Any]]:
    """
    Generate messages for implementing initial plan into Python code.
    """
    given_data_blocks = []
    for fn, summ in zip(filenames, file_summaries):
        given_data_blocks.append(f"{fn}\n{summ}")
    given_data = "\n".join(given_data_blocks)

    context_block = f"\n# Context from past runs\n{strategies}\n" if strategies else ""

    user = f"""# Given data:
{given_data}
# Plan
{plan}{context_block}
# Your task
Implement the plan with the given data.
Your response should be a single markdown Python code (wrapped in ```).
There should be no additional headings or text in your response.
All files/documents are in `data/` directory.

# CRITICAL: File Creation Rules
- ONLY create CSV files when you have data rows (len(df) > 0)
- Check data before writing: if len(df) > 0: df.to_csv("final/analysis.csv", index=False)
- Always create "final/summary.md" at the end with analysis results
- Print confirmation ONLY when files are actually created
- Use os.makedirs("final", exist_ok=True) before creating files
- NEVER create empty CSV files with only headers"""
    return [{"role": "user", "content": user}]


# Appendix G.3 — Coder agent (subsequent rounds)
def render_coder_next_prompt(
    file_summaries: List[str],
    filenames: List[str],
    base_code: str,
    previous_plans: List[str],
    current_step: str,
    guidelines: str = "",
    strategies: str = "",
) -> List[Dict[str, Any]]:
    """
    Generate messages for implementing current step pk+1 based on base code that implements previous plans.
    """
    _ = file_summaries, guidelines  # Available if needed

    given_data_blocks = []
    for fn, summ in zip(filenames, file_summaries):
        given_data_blocks.append(f"{fn}\n{summ}")
    given_data = "\n".join(given_data_blocks)

    prev_plans_str = "\n".join([f"{i+1}. {step}" for i, step in enumerate(previous_plans)])
    context_block = f"\n# Context from past runs\n{strategies}\n" if strategies else ""

    user = f"""You are an expert data analyst.
Your task is to implement the next plan with the given data.
# Given data:
{given_data}
# Base code
```python
{base_code}
```
# Previous plans
{prev_plans_str}
# Current plan to implement
{current_step}{context_block}
# Your task
Implement the current plan with the given data.
The implementation should be done based on the base code.
The base code is an implementation of the previous plans.
Your response should be a single markdown Python code (wrapped in ```python).
There should be no additional headings or text in your response.
All files/documents are in `data/` directory.

# CRITICAL: File Creation Rules
- ONLY create CSV files when you have data rows (len(df) > 0)
- Check data before writing: if len(df) > 0: df.to_csv("final/analysis.csv", index=False)
- Always create "final/summary.md" at the end with analysis results
- Print confirmation ONLY when files are actually created
- Use os.makedirs("final", exist_ok=True) before creating files
- NEVER create empty CSV files with only headers"""
    return [{"role": "user", "content": user}]


# Appendix G.4 — Verifier agent
def render_verifier_prompt(plans: List[str], code: str, result: str, question: str) -> List[Dict[str, Any]]:
    """
    Generate messages for LLM-as-judge verifier.
    """
    plans_str = "\n".join([f"{i+1}. {step}" for i, step in enumerate(plans)])
    current_step = plans[-1] if plans else ""

    user = f"""You are an expert data analyst.
Your task is to check whether the current plan and its code implementation is enough to answer the question.
# Question
{question}
# Plan
{plans_str}
# Current step
{current_step}
# Code
```python
{code}
```
# Execution result of code
{result[:2000]}
# Your task
Verify whether the current plan and its code implementation is enough to answer the question.
Your response should be one of 'Yes' or 'No'.
If it is enough to answer the question, please answer 'Yes'.
Otherwise, please answer 'No'.
Your answer (Yes/No):"""
    return [{"role": "user", "content": user}]


# Appendix G.5 — Router agent
def render_router_prompt(
    question: str,
    file_summaries: List[str],
    filenames: List[str],
    current_plans: List[str],
    result: str,
    strategies: str = "",
) -> List[Dict[str, Any]]:
    """
    Generate messages for router that decides how to refine the plan.
    """
    _ = file_summaries, filenames  # Available if needed

    plans_str = "\n".join([f"{i+1}. {step}" for i, step in enumerate(current_plans)])
    current_step = current_plans[-1] if current_plans else ""
    context_block = f"\n# Active strategies\n{strategies}\n" if strategies else ""

    user = f"""You are an expert data analyst.
Since current plan is insufficient to answer the question, your task is to decide how to refine the plan to answer the question.
# Question
{question}
# Current plans
{plans_str}
# Current step
{current_step}
# Obtained results from the current plans:
{result[:1500]}{context_block}
# Your task
Choose ONE of these options:
- Step 1, Step 2, ..., Step {len(current_plans)} — if a specific step is wrong
- Add Step — if a new step is needed
- Change Strategy — if the overall approach needs rethinking
- Rerun Analysis — if the data analysis was insufficient
- Retrieve Files — if more data files should be considered

Your response should be exactly one of the options above."""
    return [{"role": "user", "content": user}]


def render_finalizer_prompt(
    question: str,
    file_summaries: List[str],
    filenames: List[str],
    reference_code: str,
    reference_result: str,
    guidelines: str,
) -> List[Dict[str, Any]]:
    """
    Generate messages for finalizer - creates final/summary.md with analysis results.
    """
    given_data_blocks = []
    for fn, summ in zip(filenames, file_summaries):
        given_data_blocks.append(f"{fn}\n{summ}")
    given_data = "\n".join(given_data_blocks)

    user = f"""You are an expert data analyst.
Your task is to create a structured JSON output with your analysis results.

# Given data:
{given_data}

# Reference code
```python
{reference_code}
```

# Execution result of reference code
{reference_result[:2500]}

# Question
{question}

# Guidelines
{guidelines}

# Your task
Create a Python script that generates a JSON file with your analysis results.

The JSON should contain:
1. "analysis_summary": Brief text summary of findings (2-3 sentences)
2. "data": Key data points (counts, percentages, aggregations) as dict/list
3. "files_created": List of CSV/image files you created

Example:
{{
  "analysis_summary": "Found 450 machines available (59.4%). Top issue: 139 unassigned.",
  "data": {{
    "status_distribution": [{{"status": "Available", "count": 450, "pct": 59.4}}],
    "total_machines": 757
  }},
  "files_created": ["final/analysis.csv"]
}}

REQUIREMENTS:
1. Save to: final/result.json
2. Use: os.makedirs("final", exist_ok=True)
3. ONLY create CSV files when you have data rows: if len(df) > 0: df.to_csv("final/analysis.csv", index=False)
4. NEVER create empty CSV files with only headers
5. Only include files in "files_created" that you actually created with data
6. Print: print("✓ Created final/result.json")
7. Return ONLY code

All files/documents are in `data/` directory."""
    return [{"role": "user", "content": user}]


# ──────────────────────────────────────────────────────────────
# v3 prompts: parallel multi-strategy orchestration + visualization
# ──────────────────────────────────────────────────────────────


def render_strategy_generation_prompt(
    query: str,
    file_summaries: List[str],
    filenames: List[str],
    guidelines: str,
    past_strategies: str = "",
    num_strategies: int = 5,
) -> List[Dict[str, Any]]:
    given_data_blocks = []
    for fn, summ in zip(filenames, file_summaries):
        given_data_blocks.append(f"{fn}\n{summ}")
    given_data = "\n".join(given_data_blocks)
    past_block = f"\n# Strategies from past runs (for reference only)\n{past_strategies}\n" if past_strategies else ""

    user = f"""You are an expert data analyst. Your task is to generate {num_strategies} distinct analysis strategies.

# Question
{query}

# Available data
{given_data}

# Guidelines
{guidelines}{past_block}

# Your task
Generate exactly {num_strategies} different strategies to answer the question. Each strategy should take a fundamentally different approach:
- Different data transformations (aggregation vs filtering vs pivoting)
- Different statistical methods (descriptive vs inferential vs ML-based)
- Different angles of analysis (top-down vs bottom-up vs comparison-focused)

Return a JSON array of strategy descriptions. Each description should be 2-3 sentences explaining the approach.

Example format:
["Strategy 1: Aggregate data by category and compute summary statistics to identify dominant patterns...", "Strategy 2: Apply correlation analysis between numeric columns to discover hidden relationships...", ...]

Return ONLY the JSON array, no other text."""
    return [{"role": "user", "content": user}]


def render_perspective_analysis_prompt(
    query: str,
    filename: str,
    perspective: str,
    data_dir: str = "data",
) -> List[Dict[str, Any]]:
    perspective_instructions = {
        "statistical_profile": (
            "Generate a Python script that produces a STATISTICAL PROFILE of the file:\n"
            "- Column names, dtypes, row count\n"
            "- For numeric columns: min, max, mean, median, std, null count, distribution shape\n"
            "- For categorical columns: unique count, top-5 values with frequencies\n"
            "- Missing value percentages per column\n"
            "- Outlier detection (values beyond 3 std from mean)"
        ),
        "relationships_correlations": (
            "Generate a Python script that analyzes RELATIONSHIPS AND CORRELATIONS:\n"
            "- Correlation matrix for numeric columns (print top-10 strongest pairs)\n"
            "- Cross-tabulation of key categorical columns\n"
            "- Group-by aggregations that reveal patterns\n"
            "- Value distributions across categories"
        ),
        "data_quality": (
            "Generate a Python script that assesses DATA QUALITY AND INTEGRITY:\n"
            "- Duplicate row detection and counts\n"
            "- Null/missing value patterns (which columns, which rows)\n"
            "- Data type consistency (mixed types in columns)\n"
            "- Value range validation (negative values where unexpected, future dates, etc.)\n"
            "- Encoding issues or special characters"
        ),
    }
    instructions = perspective_instructions.get(perspective, perspective_instructions["statistical_profile"])

    user = f"""You are an expert data analyst.
{instructions}

# File to analyze
{filename} (located in `{data_dir}/` directory)

# Context question (for relevance)
{query}

# Requirements
- The script must be a single-file, self-contained Python program
- Print all findings to stdout in a structured, readable format
- Use pandas for data loading
- Do not use try/except to hide errors
- All files are in `{data_dir}/` directory
- Your response should contain ONLY a single code block"""
    return [{"role": "user", "content": user}]


VARIANT_HINTS = {
    "v0": "Use pandas as the primary library. Prefer DataFrame operations, groupby, pivot_table.",
    "v1": "Use numpy for numerical computation where possible. Prefer vectorized operations.",
    "v2": "Use scikit-learn utilities where applicable (preprocessing, metrics, decomposition).",
    "v3": "Use a functional approach with map/filter/reduce patterns where applicable.",
    "v4": "Prioritize visual output and summary statistics. Generate intermediate print statements.",
}


def render_code_variant_prompt(
    plan_step: str,
    file_summaries: List[str],
    filenames: List[str],
    variant_id: str,
    base_code: str = "",
    strategies: str = "",
) -> List[Dict[str, Any]]:
    given_data_blocks = []
    for fn, summ in zip(filenames, file_summaries):
        given_data_blocks.append(f"{fn}\n{summ}")
    given_data = "\n".join(given_data_blocks)
    hint = VARIANT_HINTS.get(variant_id, VARIANT_HINTS["v0"])
    context_block = f"\n# Context from past runs\n{strategies}\n" if strategies else ""
    base_block = f"\n# Base code (implement on top of this)\n```python\n{base_code}\n```\n" if base_code else ""

    user = f"""You are an expert data analyst.
# Given data
{given_data}
{base_block}
# Plan to implement
{plan_step}
{context_block}
# Implementation hint
{hint}

# Your task
Implement the plan step. Your response must be a single Python code block.
All files/documents are in `data/` directory.

# CRITICAL: File Creation Rules
- ONLY create CSV files when you have data rows (len(df) > 0)
- Use os.makedirs("final", exist_ok=True) before creating files
- Print results to stdout for verification
- NEVER create empty CSV files with only headers"""
    return [{"role": "user", "content": user}]


def render_ensemble_verifier_prompt(
    query: str,
    code: str,
    result: str,
    plans: List[str],
    perspective: str,
) -> List[Dict[str, Any]]:
    plans_str = "\n".join([f"{i+1}. {step}" for i, step in enumerate(plans)])

    perspective_instructions = {
        "statistical": (
            "Focus on STATISTICAL CORRECTNESS:\n"
            "- Are calculations correct (sums, averages, percentages)?\n"
            "- Are aggregations applied to the right columns?\n"
            "- Are results numerically plausible given the data?"
        ),
        "logical": (
            "Focus on LOGICAL COMPLETENESS:\n"
            "- Does the analysis cover all aspects of the question?\n"
            "- Are there logical gaps or missing steps?\n"
            "- Does the code handle edge cases (empty data, nulls)?"
        ),
        "query_alignment": (
            "Focus on QUERY ALIGNMENT:\n"
            "- Does the output directly answer the user's question?\n"
            "- Is the information presented in a useful format?\n"
            "- Would a human reading the output understand the answer?"
        ),
    }
    instructions = perspective_instructions.get(perspective, perspective_instructions["query_alignment"])

    user = f"""You are an expert data analyst acting as a quality reviewer.

{instructions}

# Question
{query}

# Analysis Plan
{plans_str}

# Code
```python
{code}
```

# Execution Output
{result[:2500]}

# Your task
Evaluate the analysis from your specific perspective. Respond with a JSON object:
{{"verified": true/false, "reasoning": "brief explanation", "confidence": 0.0-1.0}}

Return ONLY the JSON object."""
    return [{"role": "user", "content": user}]


def render_visualization_planner_prompt(
    query: str,
    file_summaries: List[str],
    filenames: List[str],
    execution_stdout: str,
) -> List[Dict[str, Any]]:
    given_data_blocks = []
    for fn, summ in zip(filenames, file_summaries):
        given_data_blocks.append(f"{fn}\n{summ}")
    given_data = "\n".join(given_data_blocks)

    user = f"""You are an expert data visualization specialist.

# Question
{query}

# Available data
{given_data}

# Analysis results
{execution_stdout[:2500]}

# Your task
Plan 8-12 visualizations that best communicate the analysis findings. For each chart, specify:
- chart_type: one of bar, line, scatter, heatmap, box, pie, histogram, correlation_matrix, stacked_bar, grouped_bar, area, violin
- title: descriptive chart title
- description: what insight the chart communicates (1 sentence)
- data_columns: list of column names to use
- filename: output filename (e.g., "chart_01_distribution.png")

Return a JSON array of chart specifications.

Example:
[
  {{"chart_type": "bar", "title": "Distribution by Category", "description": "Shows count of items per category", "data_columns": ["category", "count"], "filename": "chart_01_category_distribution.png"}},
  ...
]

Return ONLY the JSON array."""
    return [{"role": "user", "content": user}]


def render_chart_generation_prompt(
    chart_spec: Dict[str, Any],
    file_summaries: List[str],
    filenames: List[str],
) -> List[Dict[str, Any]]:
    given_data_blocks = []
    for fn, summ in zip(filenames, file_summaries):
        given_data_blocks.append(f"{fn}\n{summ}")
    given_data = "\n".join(given_data_blocks)
    out_filename = chart_spec.get("filename", "chart.png")

    user = f"""You are an expert data visualization engineer.

# Available data
{given_data}

# Chart specification
- Type: {chart_spec.get("chart_type", "bar")}
- Title: {chart_spec.get("title", "Chart")}
- Description: {chart_spec.get("description", "")}
- Data columns: {chart_spec.get("data_columns", [])}
- Output file: final/charts/{out_filename}

# Your task
Generate a self-contained Python script that creates this chart.

# REQUIREMENTS
1. import matplotlib; matplotlib.use('Agg')  # MUST be first matplotlib import
2. import matplotlib.pyplot as plt
3. import seaborn as sns (for enhanced styling)
4. Use pandas to load data from data/ directory
5. os.makedirs("final/charts", exist_ok=True)
6. plt.figure(figsize=(10, 6))
7. Use a clean, professional style (sns.set_theme())
8. Add proper labels, title, legend where applicable
9. plt.tight_layout()
10. plt.savefig("final/charts/{out_filename}", dpi=150, bbox_inches='tight')
11. plt.close()
12. print("Created final/charts/{out_filename}")
13. All files are in `data/` directory
14. Do NOT use plt.show()
15. Do NOT use try/except to hide errors

Return ONLY the Python code block."""
    return [{"role": "user", "content": user}]


def render_chart_quality_prompt(
    chart_spec: Dict[str, Any],
    code: str,
    execution_stdout: str,
    execution_stderr: str,
) -> List[Dict[str, Any]]:
    user = f"""You are a data visualization quality reviewer.

# Chart specification
- Type: {chart_spec.get("chart_type")}
- Title: {chart_spec.get("title")}
- Description: {chart_spec.get("description")}

# Generated code
```python
{code}
```

# Execution stdout
{execution_stdout[:1000]}

# Execution stderr
{execution_stderr[:500]}

# Your task
Evaluate the chart quality. Consider:
1. Does the code correctly load and process the data?
2. Is the chart type appropriate for the data?
3. Are labels, title, and legend present?
4. Will the output be visually clear and professional?

Respond with JSON:
{{"good": true/false, "issues": "brief description of problems if any", "revised_spec": null}}

Return ONLY the JSON object."""
    return [{"role": "user", "content": user}]


def render_report_section_prompt(
    query: str,
    section_name: str,
    insights: str,
    chart_filenames: List[str],
    execution_stdout: str = "",
) -> List[Dict[str, Any]]:
    section_instructions = {
        "executive_summary": "Write a concise 3-4 sentence executive summary. State the key conclusion and one supporting data point. MAX 100 words.",
        "key_findings": "List 3-5 key findings as bullet points. Each finding: one sentence + one number. MAX 150 words.",
        "statistical_analysis": "Present the most important statistical results in ONE compact table (max 8 rows). Add 2-3 sentences of interpretation. MAX 200 words.",
        "data_quality": "2-3 sentences on data completeness and any issues found. MAX 60 words.",
        "methodology": "1-2 sentences on the approach used. MAX 40 words.",
        "visualizations": "For each chart, write ONE sentence explaining the key takeaway. Reference as ![title](charts/filename.png). MAX 150 words.",
        "recommendations": "3-4 numbered recommendations, one sentence each. MAX 80 words.",
        "appendix": "List column names and data types in a compact table. MAX 100 words.",
    }
    instructions = section_instructions.get(section_name, f"Write the {section_name} section.")
    charts_ref = "\n".join([f"- charts/{c}" for c in chart_filenames]) if chart_filenames else "No charts available"

    user = f"""You are an expert data analyst writing a concise professional report.
CRITICAL: Keep output SHORT. Respect the MAX word count in the instructions. No filler, no repetition.

# Question
{query}

# Section: {section_name}
{instructions}

# Insights
{insights[:2000]}

# Output excerpt
{execution_stdout[:1000]}

# Charts
{charts_ref}

Write ONLY the "{section_name}" section in markdown. Be specific with numbers, not verbose with words.
For charts: ![Title](charts/filename.png)
Return ONLY markdown (no code blocks wrapping)."""
    return [{"role": "user", "content": user}]


# Appendix G.7 — Debugging agent (traceback summarization)
def render_debug_summarize_prompt(bug_traceback: str, filename: str) -> List[Dict[str, Any]]:
    """
    Summarize the error traceback; do not remove where the error occurred.
    """
    user = f"""# Error report
{bug_traceback}
# Your task
- Remove all unnecessary parts of the above error report.
- We are now running {filename}.py. Do not remove where the error occurred."""
    return [{"role": "user", "content": user}]


# Appendix G.53 — Debugger for analyzer scripts
def render_debug_fix_analyzer_prompt(code: str, summarized_bug: str) -> List[Dict[str, Any]]:
    """
    Revise analyzer script to fix error. Must return improved self-contained Python script only.
    """
    user = f"""# Code with an error:
```python
{code}
```
# Error:
{summarized_bug}
# Your task
- Please revise the code to fix the error.
- Provide the improved, self-contained Python script again.
- There should be no additional headings or text in your response.
- Do not include dummy contents since we will debug if error occurs.
- All files/documents are in `data/` directory."""
    return [{"role": "user", "content": user}]


# Appendix G.54 — Debugger for solution scripts (with data availability constraints)
def render_debug_fix_solution_prompt(
    file_summaries: List[str],
    filenames: List[str],
    code: str,
    summarized_bug: str,
) -> List[Dict[str, Any]]:
    """
    Revise solution script using data descriptions to fix error. Must return self-contained Python script only.
    """
    given_data_blocks = []
    for fn, summ in zip(filenames, file_summaries):
        given_data_blocks.append(f"{fn}\n{summ}")
    given_data = "\n".join(given_data_blocks)

    user = f"""# Given data: {", ".join(filenames)}
{given_data}
# Code with an error:
```python
{code}
```
# Error:
{summarized_bug}
# Your task
- Please revise the code to fix the error.
- Provide the improved, self-contained Python script again.
- Note that you only have {", ".join(filenames)} available.
- There should be no additional headings or text in your response.
- Do not include dummy contents since we will debug if error occurs.
- All files/documents are in `data/` directory."""
    return [{"role": "user", "content": user}]
