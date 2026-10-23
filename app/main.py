from datetime import datetime, timezone
import hashlib, json, re
from pathlib import Path
from fastapi import FastAPI, Depends, File, UploadFile, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from .database import Base, engine, get_db
from .models import DocumentVersion, DocumentNode, Selection, SelectionItem, GenerationRecord
from .schemas import SelectionCreate, GenerateRequest, IngestResponse
from .parser import parse_pdf, sha256_text
from .llm import generate_cases
from .config import GENERATED_STORE
from .versioning import compare_text

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Tri9T AI CT-200 Document QA API", version="1.0.0", description="Versioned PDF hierarchy, pinned selections, QA generation and staleness detection.")


def _generated_records():
    GENERATED_STORE.parent.mkdir(parents=True, exist_ok=True)
    if not GENERATED_STORE.exists(): return []
    try: return json.loads(GENERATED_STORE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError): return []

def _save_generated(records):
    GENERATED_STORE.parent.mkdir(parents=True, exist_ok=True)
    temp = GENERATED_STORE.with_suffix(".tmp")
    temp.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(GENERATED_STORE)

def _node_tree(db: Session, node: DocumentNode):
    children = db.scalars(select(DocumentNode).where(DocumentNode.parent_id == node.id).order_by(DocumentNode.order_index)).all()
    return {"id":node.id,"version_id":node.version_id,"logical_key":node.logical_key,"heading":node.heading,"level":node.level,"parent_id":node.parent_id,"body_text":node.body_text,"content_hash":node.content_hash,"node_type":node.node_type,"children":[{"id":c.id,"heading":c.heading,"level":c.level,"parent_id":c.parent_id,"content_hash":c.content_hash,"node_type":c.node_type} for c in children]}

@app.get("/health")
def health():
    return {"status":"ok","service":"Tri9T AI CT-200 API"}

@app.post("/documents/ingest", response_model=IngestResponse)
async def ingest_document(document_key: str = Query("ct200", min_length=1, max_length=200), version_label: str = Query(..., min_length=1, max_length=50), file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Upload a PDF file.")
    if db.scalar(select(DocumentVersion).where(DocumentVersion.document_key==document_key, DocumentVersion.version_label==version_label)):
        raise HTTPException(409, f"Version {version_label!r} already exists for {document_key!r}; choose a new version label.")
    content = await file.read()
    if not content: raise HTTPException(400, "Uploaded PDF is empty.")
    temp_path = Path("/tmp") / f"tri9t_upload_{hashlib.sha256(content).hexdigest()[:16]}.pdf"
    temp_path.write_bytes(content)
    try:
        parsed = parse_pdf(temp_path)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(422, str(exc))
    finally:
        temp_path.unlink(missing_ok=True)

    version = DocumentVersion(document_key=document_key, version_label=version_label, source_filename=file.filename)
    db.add(version); db.flush()
    ids = {}
    for item in parsed:
        parent_id = ids.get(item.parent_index) if item.parent_index is not None else None
        node = DocumentNode(version_id=version.id, logical_key=item.logical_key, heading=item.heading, level=item.level,
            body_text=item.body_text, content_hash=item.content_hash, parent_id=parent_id,
            order_index=item.order_index, node_type=item.node_type)
        db.add(node); db.flush(); ids[item.order_index] = node.id
    db.commit()
    top_count = sum(1 for n in parsed if n.parent_index is None)
    return IngestResponse(document_key=document_key, version_label=version_label, version_id=version.id, node_count=len(parsed), top_level_count=top_count, message="Ingestion completed. Review extracted hierarchy for parser limitations.")

@app.get("/documents/{document_key}/versions")
def list_versions(document_key: str, db: Session = Depends(get_db)):
    versions = db.scalars(select(DocumentVersion).where(DocumentVersion.document_key==document_key).order_by(DocumentVersion.id)).all()
    if not versions: raise HTTPException(404, "Document not found.")
    return [{"id":v.id,"document_key":v.document_key,"version_label":v.version_label,"source_filename":v.source_filename,"created_at":v.created_at} for v in versions]

@app.get("/documents/{document_key}/sections")
def list_top_sections(document_key: str, version: str | None = None, db: Session = Depends(get_db)):
    versions = db.scalars(select(DocumentVersion).where(DocumentVersion.document_key==document_key).order_by(DocumentVersion.id.desc())).all()
    if not versions: raise HTTPException(404, "Document not found.")
    selected = next((v for v in versions if v.version_label==version), None) if version else versions[0]
    if selected is None: raise HTTPException(404, "Requested version not found.")
    nodes = db.scalars(select(DocumentNode).where(DocumentNode.version_id==selected.id, DocumentNode.parent_id.is_(None)).order_by(DocumentNode.order_index)).all()
    return {"document_key":document_key,"version":selected.version_label,"sections":[{"id":n.id,"heading":n.heading,"level":n.level,"content_hash":n.content_hash,"node_type":n.node_type} for n in nodes]}

@app.get("/nodes/{node_id}")
def get_node(node_id: int, db: Session = Depends(get_db)):
    node = db.get(DocumentNode, node_id)
    if not node: raise HTTPException(404, "Node not found.")
    return _node_tree(db, node)

@app.get("/search")
def search_nodes(q: str = Query(..., min_length=1), document_key: str | None = None, version: str | None = None, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    query = select(DocumentNode).join(DocumentVersion).where((DocumentNode.heading.ilike(f"%{q}%")) | (DocumentNode.body_text.ilike(f"%{q}%")))
    if document_key: query = query.where(DocumentVersion.document_key==document_key)
    if version: query = query.where(DocumentVersion.version_label==version)
    nodes = db.scalars(query.order_by(DocumentNode.id).limit(limit)).all()
    return {"query":q,"count":len(nodes),"results":[{"id":n.id,"version_id":n.version_id,"version":n.version.version_label,"document_key":n.version.document_key,"heading":n.heading,"level":n.level,"parent_id":n.parent_id,"content_hash":n.content_hash,"snippet":n.body_text[:240]} for n in nodes]}

@app.get("/nodes/{node_id}/changes")
def node_changes(node_id: int, db: Session = Depends(get_db)):
    node = db.get(DocumentNode, node_id)
    if not node: raise HTTPException(404, "Node not found.")
    peers = db.scalars(select(DocumentNode).join(DocumentVersion).where(DocumentVersion.document_key==node.version.document_key, DocumentNode.logical_key==node.logical_key).order_by(DocumentNode.version_id)).all()
    results=[]
    for peer in peers:
        results.append({"node_id":peer.id,"version":peer.version.version_label,"content_hash":peer.content_hash,"changed_from_requested_node":peer.content_hash != node.content_hash,"diff":compare_text(node.body_text, peer.body_text)})
    return {"requested_node_id":node.id,"logical_key":node.logical_key,"versions_found":len(results),"comparisons":results,"note":"Matching is heuristic; identical titles moved between branches or duplicated ambiguously may not match."}

@app.post("/selections", status_code=201)
def create_selection(payload: SelectionCreate, db: Session = Depends(get_db)):
    nodes=[]
    for node_id in payload.node_ids:
        node=db.get(DocumentNode,node_id)
        if not node: raise HTTPException(404, f"Node {node_id} not found.")
        nodes.append(node)
    selection=Selection(name=payload.name); db.add(selection); db.flush()
    for node in nodes:
        db.add(SelectionItem(selection_id=selection.id,node_id=node.id,version_id=node.version_id,source_heading=node.heading,source_text=node.body_text,source_hash=node.content_hash))
    db.commit()
    return {"id":selection.id,"name":selection.name,"created_at":selection.created_at,"items":[{"node_id":i.node_id,"version_id":i.version_id,"version":db.get(DocumentVersion,i.version_id).version_label,"heading":i.source_heading,"content_hash":i.source_hash} for i in selection.items]}

@app.get("/selections/{selection_id}")
def get_selection(selection_id: int, db: Session = Depends(get_db)):
    selection=db.get(Selection,selection_id)
    if not selection: raise HTTPException(404,"Selection not found.")
    return {"id":selection.id,"name":selection.name,"created_at":selection.created_at,"items":[{"node_id":i.node_id,"version_id":i.version_id,"version":db.get(DocumentVersion,i.version_id).version_label,"heading":i.source_heading,"source_text":i.source_text,"source_hash":i.source_hash} for i in selection.items]}

@app.post("/generations", status_code=201)
async def generate(payload: GenerateRequest, db: Session = Depends(get_db)):
    selection=db.get(Selection,payload.selection_id)
    if not selection: raise HTTPException(404,"Selection not found.")
    items=selection.items
    if not items: raise HTTPException(422,"Selection has no items.")
    source="\n\n".join(f"Section: {i.source_heading}\nVersion-pinned source text:\n{i.source_text}\nSource hash: {i.source_hash}" for i in items)
    fingerprint=hashlib.sha256("|".join(sorted(i.source_hash for i in items)).encode()).hexdigest()
    records=_generated_records()
    if not payload.regenerate:
        existing=next((r for r in records if r["selection_id"]==selection.id and r["source_fingerprint"]==fingerprint),None)
        if existing:
            existing["duplicate_policy"]="Returned existing generation for same selection and exact source fingerprint. Set regenerate=true to create a new run."
            return existing
    try:
        output, provider=await generate_cases(source)
    except Exception as exc:
        raise HTTPException(502, f"Generation failed safely: {exc}")
    record={"id":hashlib.sha256(f"{selection.id}:{fingerprint}:{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()[:20],"selection_id":selection.id,"selection_name":selection.name,"created_at":datetime.now(timezone.utc).isoformat(),"source_fingerprint":fingerprint,"source_snapshot":[{"node_id":i.node_id,"version_id":i.version_id,"heading":i.source_heading,"text":i.source_text,"content_hash":i.source_hash} for i in items],"provider":provider,"test_cases":output["test_cases"],"duplicate_policy":"Same selection and same source fingerprint returns existing result unless regenerate=true."}
    records.append(record); _save_generated(records)
    db.add(GenerationRecord(selection_id=selection.id,store_key=record["id"],source_fingerprint=fingerprint,status="valid")); db.commit()
    return record

@app.get("/generations")
def retrieve_generations(selection_id: int | None = None, node_id: int | None = None, db: Session = Depends(get_db)):
    if selection_id is None and node_id is None: raise HTTPException(422,"Provide selection_id or node_id.")
    records=_generated_records(); result=[]
    for record in records:
        if selection_id is not None and record["selection_id"] != selection_id: continue
        if node_id is not None and not any(s["node_id"]==node_id for s in record["source_snapshot"]): continue
        stale_items=[]
        for source in record["source_snapshot"]:
            old_node=db.get(DocumentNode,source["node_id"])
            if not old_node:
                stale_items.append({"node_id":source["node_id"],"stale":True,"reason":"Original node missing"}); continue
            latest=db.scalars(select(DocumentNode).join(DocumentVersion).where(DocumentVersion.document_key==old_node.version.document_key,DocumentNode.logical_key==old_node.logical_key).order_by(DocumentNode.version_id.desc())).first()
            stale=latest is None or latest.content_hash != source["content_hash"]
            stale_items.append({"node_id":source["node_id"],"latest_node_id":latest.id if latest else None,"source_version":old_node.version.version_label,"latest_version":latest.version.version_label if latest else None,"stale":stale,"diff":compare_text(source["text"],latest.body_text) if latest else None})
        record_copy=dict(record); record_copy["staleness"]={"is_stale":any(x["stale"] for x in stale_items),"items":stale_items,"method":"Exact content hash comparison on heuristic logical-key match; wording changes and clinically significant changes both flag stale. Semantic/risk-aware analysis is not implemented."}
        result.append(record_copy)
    return {"count":len(result),"generations":result}

@app.get("/generations/{generation_id}")
def get_generation(generation_id: str, db: Session = Depends(get_db)):
    records=_generated_records()
    if not any(r["id"]==generation_id for r in records): raise HTTPException(404,"Generation not found.")
    # Reuse the retrieval route's staleness logic through the source selection.
    record=next(r for r in records if r["id"]==generation_id)
    response = retrieve_generations(selection_id=record["selection_id"], node_id=None, db=db)
    return {"count": sum(1 for item in response["generations"] if item["id"] == generation_id), "generations": [item for item in response["generations"] if item["id"] == generation_id]}
