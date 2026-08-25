; SEMLock TypeScript spike query spec (S3).
; Declarative mirror of extractor.py's tree-walk. Kept as documentation and
; exercised by test_extraction_kinds.py::test_query_spec_compiles so grammar
; field-name drift fails CI loudly. Extraction itself uses the deterministic
; walk in extractor.py (spike: one code path to audit).

(function_declaration
  name: (identifier) @function.name) @function.def

(class_declaration
  name: (type_identifier) @class.name) @class.def

(interface_declaration
  name: (type_identifier) @interface.name) @interface.def

(type_alias_declaration
  name: (type_identifier) @type_alias.name) @type_alias.def

(method_definition
  name: (property_identifier) @method.name) @method.def

(public_field_definition
  name: (property_identifier) @field.name) @field.def

(property_signature
  name: (property_identifier) @property.name) @property.def

(method_signature
  name: (property_identifier) @signature_method.name) @signature_method.def

(lexical_declaration
  (variable_declarator
    name: (identifier) @variable.name
    value: (arrow_function))) @arrow_const.def

(call_expression
  function: (identifier) @call.callee)

(new_expression
  constructor: (identifier) @ctor.callee)

(member_expression
  property: (property_identifier) @member.prop)

(import_statement
  (import_clause
    (named_imports
      (import_specifier
        name: (identifier) @import.original))))

(export_statement (export_clause)) @reexport.clause

(class_heritage
  (extends_clause) @extends.clause
  (implements_clause) @implements.clause)
