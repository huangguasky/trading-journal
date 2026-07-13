# Development Instructions

## Python Environment

- This project uses the Conda environment named `tj`.
- Run all Python commands through `conda run -n tj`.
- Start the Python engine with `conda run -n tj python -m engine.app`.
- Run command-line analysis with `conda run -n tj python -m engine.runtime ...`.
- Run Python tests with `conda run -n tj python -m pytest`.
- Do not use the system Python or install project dependencies globally.
- Install project dependencies into the environment with
  `conda run -n tj python -m pip install -e ".[data,llm,dev]"`.
