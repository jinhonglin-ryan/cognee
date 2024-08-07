import asyncio
import logging
from typing import Union

from cognee.infrastructure.databases.graph import get_graph_config
from cognee.modules.cognify.config import get_cognify_config
from cognee.infrastructure.databases.relational import get_relational_engine
from cognee.modules.data.processing.document_types.AudioDocument import AudioDocument
from cognee.modules.data.processing.document_types.ImageDocument import ImageDocument
from cognee.shared.data_models import KnowledgeGraph
from cognee.modules.data.processing.document_types import PdfDocument, TextDocument
# from cognee.modules.cognify.vector import save_data_chunks
# from cognee.modules.data.processing.process_documents import process_documents
# from cognee.modules.classification.classify_text_chunks import classify_text_chunks
# from cognee.modules.data.extraction.data_summary.summarize_text_chunks import summarize_text_chunks
# from cognee.modules.data.processing.filter_affected_chunks import filter_affected_chunks
# from cognee.modules.data.processing.remove_obsolete_chunks import remove_obsolete_chunks
# from cognee.modules.data.extraction.knowledge_graph.expand_knowledge_graph import expand_knowledge_graph
# from cognee.modules.data.extraction.knowledge_graph.establish_graph_topology import establish_graph_topology
from cognee.modules.data.models import Dataset, Data
from cognee.modules.data.operations.get_dataset_data import get_dataset_data
from cognee.modules.data.operations.retrieve_datasets import retrieve_datasets
from cognee.modules.pipelines.tasks.Task import Task
from cognee.modules.pipelines import run_tasks, run_tasks_parallel
from cognee.modules.users.models import User
from cognee.modules.users.methods import get_default_user
from cognee.modules.users.permissions.methods import check_permissions_on_documents
from cognee.modules.pipelines.operations.get_pipeline_status import get_pipeline_status
from cognee.modules.pipelines.operations.log_pipeline_status import log_pipeline_status
from cognee.tasks.chunk_extract_summary.chunk_extract_summary import chunk_extract_summary_task
from cognee.tasks.chunk_naive_llm_classifier.chunk_naive_llm_classifier import chunk_naive_llm_classifier_task
from cognee.tasks.chunk_remove_disconnected.chunk_remove_disconnected import chunk_remove_disconnected_task
from cognee.tasks.chunk_to_graph_decomposition.chunk_to_graph_decomposition import chunk_to_graph_decomposition_task
from cognee.tasks.chunk_to_vector_graphstore.chunk_to_vector_graphstore import chunk_to_vector_graphstore_task
from cognee.tasks.chunk_update_check.chunk_update_check import chunk_update_check_task
from cognee.tasks.graph_decomposition_to_graph_nodes.graph_decomposition_to_graph_nodes import \
    graph_decomposition_to_graph_nodes_task
from cognee.tasks.source_documents_to_chunks.source_documents_to_chunks import source_documents_to_chunks

logger = logging.getLogger("cognify.v2")

update_status_lock = asyncio.Lock()

class PermissionDeniedException(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)

async def cognify(datasets: Union[str, list[str]] = None, user: User = None):
    db_engine = get_relational_engine()

    if datasets is None or len(datasets) == 0:
        return await cognify(await db_engine.get_datasets())

    if type(datasets[0]) == str:
        datasets = await retrieve_datasets(datasets)

    if user is None:
        user = await get_default_user()

    async def run_cognify_pipeline(dataset: Dataset):
        data: list[Data] = await get_dataset_data(dataset_id = dataset.id)

        documents = [
            PdfDocument(id = data_item.id, title=f"{data_item.name}.{data_item.extension}", file_path=data_item.raw_data_location) if data_item.extension == "pdf" else
            AudioDocument(id = data_item.id, title=f"{data_item.name}.{data_item.extension}", file_path=data_item.raw_data_location) if data_item.extension == "audio" else
            ImageDocument(id = data_item.id, title=f"{data_item.name}.{data_item.extension}", file_path=data_item.raw_data_location) if data_item.extension == "image" else
            TextDocument(id = data_item.id, title=f"{data_item.name}.{data_item.extension}", file_path=data_item.raw_data_location)
            for data_item in data
        ]

        document_ids = [document.id for document in documents]
        document_ids_str = list(map(str, document_ids))

        await check_permissions_on_documents(
            user,
            "read",
            document_ids,
        )

        dataset_id = dataset.id
        dataset_name = generate_dataset_name(dataset.name)

        async with update_status_lock:
            task_status = await get_pipeline_status([dataset_id])

            if dataset_id in task_status and task_status[dataset_id] == "DATASET_PROCESSING_STARTED":
                logger.info("Dataset %s is already being processed.", dataset_name)
                return

            await log_pipeline_status(dataset_id, "DATASET_PROCESSING_STARTED", {
                "dataset_name": dataset_name,
                "files": document_ids_str,
            })
        try:
            cognee_config = get_cognify_config()
            graph_config = get_graph_config()
            root_node_id = None

            if graph_config.infer_graph_topology and graph_config.graph_topology_task:
                from cognee.modules.topology.topology import TopologyEngine
                topology_engine = TopologyEngine(infer=graph_config.infer_graph_topology)
                root_node_id = await topology_engine.add_graph_topology(files = data)
            elif graph_config.infer_graph_topology and not graph_config.infer_graph_topology:
                from cognee.modules.topology.topology import TopologyEngine
                topology_engine = TopologyEngine(infer=graph_config.infer_graph_topology)
                await topology_engine.add_graph_topology(graph_config.topology_file_path)
            elif not graph_config.graph_topology_task:
                root_node_id = "ROOT"

            tasks = [
                Task(source_documents_to_chunks, parent_node_id = root_node_id), # Classify documents and save them as a nodes in graph db, extract text chunks based on the document type
                Task(chunk_to_graph_decomposition_task, topology_model = KnowledgeGraph, task_config = { "batch_size": 10 }), # Set the graph topology for the document chunk data
                Task(graph_decomposition_to_graph_nodes_task, graph_model = KnowledgeGraph, collection_name = "entities"), # Generate knowledge graphs from the document chunks and attach it to chunk nodes
                Task(chunk_update_check_task, collection_name = "chunks"), # Find all affected chunks, so we don't process unchanged chunks
                Task(
                    chunk_to_vector_graphstore_task,
                    collection_name = "chunks",
                ), # Save the document chunks in vector db and as nodes in graph db (connected to the document node and between each other)
                run_tasks_parallel([
                    Task(
                        chunk_extract_summary_task,
                        summarization_model = cognee_config.summarization_model,
                        collection_name = "chunk_summaries",
                    ), # Summarize the document chunks
                    Task(
                        chunk_naive_llm_classifier_task,
                        classification_model = cognee_config.classification_model,
                    ),
                ]),
                Task(chunk_remove_disconnected_task), # Remove the obsolete document chunks.
            ]

            pipeline = run_tasks(tasks, documents)

            async for result in pipeline:
                print(result)

            await log_pipeline_status(dataset_id, "DATASET_PROCESSING_FINISHED", {
                "dataset_name": dataset_name,
                "files": document_ids_str,
            })
        except Exception as error:
            await log_pipeline_status(dataset_id, "DATASET_PROCESSING_ERROR", {
                "dataset_name": dataset_name,
                "files": document_ids_str,
            })
            raise error


    existing_datasets = [dataset.name for dataset in list(await db_engine.get_datasets())]
    awaitables = []

    for dataset in datasets:
        dataset_name = generate_dataset_name(dataset.name)

        if dataset_name in existing_datasets:
            awaitables.append(run_cognify_pipeline(dataset))

    return await asyncio.gather(*awaitables)


def generate_dataset_name(dataset_name: str) -> str:
    return dataset_name.replace(".", "_").replace(" ", "_")
