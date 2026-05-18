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
