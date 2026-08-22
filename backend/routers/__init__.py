"""One router module per resource.

Split by resource rather than kept in a single main.py because each of these
has genuinely different failure modes -- upload deals with multipart and file
size, world deals with per-archetype parameters, chat deals with an external
API that is allowed to be down -- and mixing them produces a file where the
error handling for one endpoint is three screens from the endpoint itself.
"""
