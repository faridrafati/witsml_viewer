"""WITSML 1.4.1.1 protocol layer.

Isolated and independently testable from api/ and ws/ (see brief §10).
Public surface: constants, queries (QBE builders), parse (XML->domain),
client (SOAP gateway). queries/parse import only lxml + domain + constants,
so they can be unit-tested without zeep or a live server.
"""
