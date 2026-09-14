import sys
sys.path.insert(0,"/projects")
from contract_task_contract import TaskContract
from contract_evidence_contract import EvidenceArtifact

def test_task_contract_strict():
    t = TaskContract(
        goal="Reload credentials safely",
        constraints=("No secret exposure",),
        dependencies=(),
        file_scope=("credential_pool_manager.py",),
        acceptance_criteria=("Fingerprint only",),
        required_work_products=("WorkerWorkProduct",),
        input_references=("connection_manager.read_secret_source",),
        validation_requirements=("passed=True",),
        capabilities=("credential_rebind",),
    )
    try:
        TaskContract.from_dict({"goal":"ok","constraints":["a",123],"dependencies":["b"],"file_scope":["c"],"acceptance_criteria":["d"],"required_work_products":["e"],"input_references":["f"],"validation_requirements":["g"],"capabilities":["h"]})
        assert False, "should reject non-string constraint"
    except ValueError as e:
        assert "non-string" in str(e)
    try:
        TaskContract.from_dict({"goal":123,"constraints":["a"],"dependencies":["b"],"file_scope":["c"],"acceptance_criteria":["d"],"required_work_products":["e"],"input_references":["f"],"validation_requirements":["g"]})
        assert False
    except ValueError:
        pass
    try:
        TaskContract.from_dict({"goal":"ok","constraints":"bad","dependencies":["b"],"file_scope":["c"],"acceptance_criteria":["d"],"required_work_products":["e"],"input_references":["f"],"validation_requirements":["g"]})
        assert False
    except ValueError as e:
        assert "sequence" in str(e)
    try:
        TaskContract.from_dict({"goal":"ok","constraints":[""],"dependencies":["b"],"file_scope":["c"],"acceptance_criteria":["d"],"required_work_products":["e"],"input_references":["f"],"validation_requirements":["g"]})
        assert False
    except ValueError as e:
        assert "empty" in str(e)
    print("PASS: task_contract_strict")

def test_evidence_contract_semantics():
    art = EvidenceArtifact(status="SUCCEEDED", fingerprint="sha256:ok", checkpoint_id="chk-01", validation_evidence={"passed":True,"checkpoint_id":"chk-01"}, failure=None)
    try:
        EvidenceArtifact.from_dict({"status":"FAILED","fingerprint":"sha256:fail","checkpoint_id":"chk-02","validation_evidence":{"passed":True,"checkpoint_id":"chk-02"},"failure":{"message":"bad"}})
        assert False, "FAILED with passed=True rejected"
    except ValueError as e:
        assert "passed=True" in str(e)
    try:
        EvidenceArtifact.from_dict({"status":"FAILED","fingerprint":"sha256:fail","checkpoint_id":"chk-02","validation_evidence":{"passed":False,"checkpoint_id":"chk-02"}})
        assert False, "FAILED without message"
    except ValueError as e:
        assert "message" in str(e)
    try:
        EvidenceArtifact.from_dict({"status":"SAFE_STOP","fingerprint":"sha256:stop","checkpoint_id":"chk-03","validation_evidence":{"passed":True,"checkpoint_id":"chk-03","reason":"timeout"}})
        assert False, "SAFE_STOP with passed=True"
    except ValueError as e:
        assert "passed=True" in str(e)
    try:
        EvidenceArtifact.from_dict({"status":"SAFE_STOP","fingerprint":"sha256:stop","checkpoint_id":"chk-03","validation_evidence":{"passed":False,"checkpoint_id":"chk-03"}})
        assert False, "SAFE_STOP missing reason"
    except ValueError as e:
        assert "SAFE_STOP" in str(e)
    try:
        EvidenceArtifact.from_dict({"status":"SUCCEEDED","fingerprint":"sk-secret","checkpoint_id":"chk-01","validation_evidence":{"passed":True,"checkpoint_id":"chk-01"}})
        assert False, "secret fingerprint"
    except ValueError as e:
        assert "fingerprint" in str(e)
    try:
        EvidenceArtifact.from_dict({"status":"SUCCEEDED","fingerprint":"sha256:ok","checkpoint_id":"","validation_evidence":{"passed":True,"checkpoint_id":"chk-01"}})
        assert False, "empty checkpoint"
    except ValueError:
        pass
    print("PASS: evidence_contract_semantics")

def test_integration_with_existing_authorities():
    content_task = open("/projects/contract_task_contract.py").read()
    content_evidence = open("/projects/contract_evidence_contract.py").read()
    assert "class IndependentValidator" not in content_task
    assert "class ExecutionAuthorizationBoundary" not in content_task
    assert "class ExecutionGate" not in content_task
    assert "class GitMutationExecutor" not in content_task
    assert "class WorkerWorkProduct" not in content_task
    assert "WorkerWorkProduct" in open("/projects/WORKER_WORK_PRODUCT_PROTOCOL.md").read()
    assert "IndependentValidator" in open("/projects/independent_validation.py").read()
    assert "ExecutionAuthorizationBoundary" in open("/projects/execution_authorization.py").read()
    print("PASS: integration_with_existing_authorities")

if __name__ == "__main__":
    test_task_contract_strict()
    test_evidence_contract_semantics()
    test_integration_with_existing_authorities()
    print("ALL CONTRACT TESTS PASS")
