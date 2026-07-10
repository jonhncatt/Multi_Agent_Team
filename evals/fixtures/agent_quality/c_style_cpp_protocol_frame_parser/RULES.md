# Implementation rules

The production file has a `.cpp` suffix, but this project intentionally uses a procedural C-style subset.

- Modify only `src/frame_parser.cpp`.
- Do not change the public header or tests.
- Use plain functions, POD structs, pointers, fixed-size arrays, loops, and explicit error codes.
- Do not use classes, templates, namespaces, STL containers or strings, exceptions, RTTI, virtual dispatch, lambdas, or dynamic allocation.
- Do not call `malloc`, `calloc`, `realloc`, `free`, `new`, or `delete`.
- Do not use global mutable state.
- Do not cast away `const`.
- The function must not write to `out_frame` until all validation has succeeded.
- Keep the implementation compatible with conservative C++ compilers; do not rely on recent language features.
