from cognee.tasks.chunks import chunk_by_paragraph

GROUND_TRUTH = {
    "whole_text": [
        {
            "text": "This is example text. It contains multiple sentences.\n",
            "word_count": 9,
            "cut_type": "paragraph_end",
        },
        {
            "text": "This is a second paragraph. First two paragraphs are whole.\n",
            "word_count": 11,
            "cut_type": "paragraph_end",
        },
        {
            "text": "Third paragraph is a bit longer and is finished with a dot.",
            "word_count": 12,
            "cut_type": "sentence_end",
        },
    ],
    "cut_text": [
        {
            "text": "This is example text. It contains multiple sentences.\n",
            "word_count": 9,
            "cut_type": "paragraph_end",
        },
        {
            "text": "This is a second paragraph. First two paragraphs are whole.\n",
            "word_count": 11,
            "cut_type": "paragraph_end",
        },
        {
            "text": "Third paragraph is cut and is missing the dot at the end",
            "word_count": 12,
            "cut_type": "word",
        },
    ],
}

INPUT_TEXT = {
    "whole_text": """This is example text. It contains multiple sentences.
This is a second paragraph. First two paragraphs are whole.
Third paragraph is a bit longer and is finished with a dot.""",
    "cut_text": """This is example text. It contains multiple sentences.
This is a second paragraph. First two paragraphs are whole.
Third paragraph is cut and is missing the dot at the end""",
}


def run_chunking_test(test_text, expected_chunks):
    chunks = []
    for chunk_data in chunk_by_paragraph(test_text, 12, batch_paragraphs=False):
        chunks.append(chunk_data)

    assert len(chunks) == 3

    for expected_chunks_item, chunk in zip(expected_chunks, chunks):
        for key in ["text", "word_count", "cut_type"]:
            assert (
                chunk[key] == expected_chunks_item[key]
            ), f"{key = }: {chunk[key] = } != {expected_chunks_item[key] = }"


def test_chunking_whole_text():
    run_chunking_test(INPUT_TEXT["whole_text"], GROUND_TRUTH["whole_text"])


def test_chunking_cut_text():
    run_chunking_test(INPUT_TEXT["cut_text"], GROUND_TRUTH["cut_text"])
