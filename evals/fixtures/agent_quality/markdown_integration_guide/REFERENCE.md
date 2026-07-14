# Supported Workflow

Build command:

```text
cmake --build build --config Release
```

Validation command:

```text
ctest --test-dir build -C Release --output-on-failure
```

The build supports Windows with MSVC 2022 and Linux with Clang 18. Existing C callers remain source-compatible; no public header changes are required.
