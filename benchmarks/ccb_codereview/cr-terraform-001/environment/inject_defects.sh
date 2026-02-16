#!/bin/bash
# Inject defects into the Terraform codebase for code review benchmarking
# Each defect simulates a realistic bug that an AI code reviewer should catch
# 6 defects across 4 files, 3 require cross-file reasoning

set -e
cd /workspace

# ── Defect 1: Invert walkValidate check in GetInputVariable ──
# Cross-file: During the validate walk, GetInputVariable should return unknown
# values so that validation checks all possible inputs. Inverting this causes
# the validate walk to use actual variable values (skipping unknown-value
# validation) and the plan walk to return unknown values (breaking planning).
# Affects context_plan.go which runs walkValidate to pre-check configurations.
python3 -c "
path = 'internal/terraform/evaluate.go'
with open(path) as f:
    content = f.read()

old = '''	if d.Operation == walkValidate {
		// We should still capture the statically-configured marks during
		// the validate walk.
		ret := cty.UnknownVal(config.Type)'''

new = '''	if d.Operation != walkValidate {
		// We should still capture the statically-configured marks during
		// the validate walk.
		ret := cty.UnknownVal(config.Type)'''

assert old in content, f'Could not find defect-1 target in {path}'
content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-1: inverted walkValidate check in GetInputVariable')
"

# ── Defect 2: Invert config nil check in GetInputVariable ──
# When a variable is referenced that isn't declared in configuration,
# config will be nil. The original code returns an error diagnostic.
# Inverting this causes declared variables to be treated as undeclared
# (returning DynamicVal with an error) and undeclared variables to
# silently pass through to NamedValues.GetInputVariableValue (panic).
python3 -c "
path = 'internal/terraform/evaluate.go'
with open(path) as f:
    content = f.read()

old = '''	config := moduleConfig.Module.Variables[addr.Name]
	if config == nil {
		var suggestions []string
		for k := range moduleConfig.Module.Variables {
			suggestions = append(suggestions, k)
		}'''

new = '''	config := moduleConfig.Module.Variables[addr.Name]
	if config != nil {
		var suggestions []string
		for k := range moduleConfig.Module.Variables {
			suggestions = append(suggestions, k)
		}'''

assert old in content, f'Could not find defect-2 target in {path}'
content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-2: inverted config nil check in GetInputVariable')
"

# ── Defect 3: Invert hasUnknownKeys check in GetResource ──
# When a resource has unknown for_each/count keys (deferred), GetResource
# should return DynamicVal since the result type is unpredictable. Inverting
# this causes resources with KNOWN keys to return DynamicVal (breaking all
# normal resource references) and resources with UNKNOWN keys to attempt
# full evaluation (causing type errors or panics).
python3 -c "
path = 'internal/terraform/evaluate.go'
with open(path) as f:
    content = f.read()

old = '''	if d.Operation == walkPlan || d.Operation == walkApply {
		if _, _, hasUnknownKeys := d.Evaluator.Instances.ResourceInstanceKeys(addr.Absolute(moduleAddr)); hasUnknownKeys {'''

new = '''	if d.Operation == walkPlan || d.Operation == walkApply {
		if _, _, hasUnknownKeys := d.Evaluator.Instances.ResourceInstanceKeys(addr.Absolute(moduleAddr)); !hasUnknownKeys {'''

assert old in content, f'Could not find defect-3 target in {path}'
content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-3: inverted hasUnknownKeys check in GetResource')
"

# ── Defect 4: Invert Ephemeral check in prepareFinalInputVariableValue ──
# Cross-file: When a variable is declared ephemeral, its value gets the
# Ephemeral mark so downstream consumers handle it correctly. Inverting
# this marks NON-ephemeral variables as ephemeral (breaking all normal
# variable references that try to persist values) and leaves ephemeral
# variables UNMARKED (leaking ephemeral data to state and outputs).
# This interacts with evaluate.go's GetInputVariable which also checks
# config.Ephemeral — but eval_variable.go runs first during preparation.
python3 -c "
path = 'internal/terraform/eval_variable.go'
with open(path) as f:
    content = f.read()

old = '''	if cfg.Ephemeral {
		// An ephemeral input variable always has an ephemeral value inside the
		// module, even if the value assigned to it from outside is not. This
		// is a useful simplification so that module authors can be explicit
		// about what guarantees they are intending to make (regardless of
		// current implementation details). Changing the ephemerality of an
		// input variable is a breaking change to a module's API.
		val = val.Mark(marks.Ephemeral)
	} else {'''

new = '''	if !cfg.Ephemeral {
		// An ephemeral input variable always has an ephemeral value inside the
		// module, even if the value assigned to it from outside is not. This
		// is a useful simplification so that module authors can be explicit
		// about what guarantees they are intending to make (regardless of
		// current implementation details). Changing the ephemerality of an
		// input variable is a breaking change to a module's API.
		val = val.Mark(marks.Ephemeral)
	} else {'''

assert old in content, f'Could not find defect-4 target in {path}'
content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-4: inverted Ephemeral check in prepareFinalInputVariableValue')
"

# ── Defect 5: Remove apply-time variable validation in ApplyAndEval ──
# Cross-file: checkApplyTimeVariables validates that all ephemeral variables
# declared in the plan are provided at apply-time. Removing this allows
# apply to proceed with missing ephemeral variables, causing panics in
# evaluate.go's GetInputVariable when it tries to read their values
# from NamedValues (which never got populated for the missing variables).
python3 -c "
path = 'internal/terraform/context_apply.go'
with open(path) as f:
    content = f.read()

old = '''	diags = diags.Append(checkApplyTimeVariables(plan.ApplyTimeVariables, opts.SetVariables, config))

	if diags.HasErrors() {
		return nil, nil, diags
	}

	for _, rc := range plan.Changes.Resources {'''

new = '''	// Apply-time variable check handled by graph walk validation.

	for _, rc := range plan.Changes.Resources {'''

assert old in content, f'Could not find defect-5 target in {path}'
content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-5: removed apply-time variable validation from ApplyAndEval')
"

# ── Defect 6: Swap HookActionContinue to HookActionHalt in NilHook.PreApply ──
# Cross-file: NilHook is embedded by all hook implementations that only
# need to override some methods. Returning HookActionHalt from PreApply
# causes every resource apply operation to abort before executing — the
# hook dispatch in node_resource_apply_instance.go checks the return value
# and halts if any hook returns HookActionHalt. This silently prevents
# all resource applications without producing an error diagnostic.
python3 -c "
path = 'internal/terraform/hook.go'
with open(path) as f:
    content = f.read()

old = '''func (*NilHook) PreApply(id HookResourceIdentity, dk addrs.DeposedKey, action plans.Action, priorState, plannedNewState cty.Value) (HookAction, error) {
	return HookActionContinue, nil
}'''

new = '''func (*NilHook) PreApply(id HookResourceIdentity, dk addrs.DeposedKey, action plans.Action, priorState, plannedNewState cty.Value) (HookAction, error) {
	return HookActionHalt, nil
}'''

assert old in content, f'Could not find defect-6 target in {path}'
content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-6: NilHook.PreApply returns HookActionHalt instead of HookActionContinue')
"

echo "All 6 defects injected successfully"
