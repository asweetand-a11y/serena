# BSL Test Repository

This is a test repository for BSL (1C:Enterprise) language support in Serena.

## Files

- **Main.bsl** - Main module demonstrating functions, procedures, and regions
- **Utils.bsl** - Utility functions for string and collection operations
- **Models.bsl** - Data structure models and manipulation functions

## Purpose

This repository is used for testing the BSL language server integration with Serena, including:

- Document symbol detection (functions, procedures, regions)
- Cross-file references
- Code completion
- Go to definition
- Find references

## Running Tests

To run BSL language server tests:

```bash
# Run all BSL tests
pytest test/solidlsp/bsl/ -v -m bsl

# Run specific test
pytest test/solidlsp/bsl/test_bsl_basic.py::TestBSLLanguageServerBasics::test_bsl_language_server_initialization -v
```

## Requirements

- Java 11+ (for bsl-language-server)
- bsl-language-server.jar in tools/ directory or configured path












