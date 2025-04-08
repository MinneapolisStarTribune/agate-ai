# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Run Commands
- Run locally: `cd bin && ./run-local.sh`
- Start service: `docker-compose up --build`
- Stop service: `docker-compose down`
- Run tests: `python -m evals.classify` or `python -m evals.extract`
- Format code: Follow PEP 8 style guide

## Code Style Guidelines
- **Imports**: Standard library first, then third-party, then local modules
- **Formatting**: 4-space indentation, 80-character line limit
- **Naming**: snake_case for variables/functions, CamelCase for classes
- **Error handling**: Use try/except with specific exceptions, log errors
- **Types**: Use docstrings to document function parameters and return types
- **Logging**: Use standard Python logging module, not print statements
- **Structure**: Organize related functionality in modules within packages
- **Documentation**: Document classes and functions using docstrings