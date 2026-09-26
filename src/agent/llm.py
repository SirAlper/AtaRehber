import os
import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    pipeline,
)
from langchain_huggingface import ChatHuggingFace, HuggingFacePipeline
from src.core.config import (
    LLM_BACKEND,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    LLM_MODEL_NAME,
    USE_4BIT_QUANTIZATION,
)
from src.core.logger import get_logger

logger = get_logger("LLM")


def create_chat_model():
    """Load chat model based on configured LLM_BACKEND ('ollama' or 'huggingface').

    The returned object implements standard LangChain ChatModel interfaces:
        - chat_model.invoke(messages)  -> Batch response
        - chat_model.stream(messages)  -> Token stream
        - chat_model.bind_tools(tools) -> Tool binding
    """
    if LLM_BACKEND == "ollama":
        from langchain_ollama import ChatOllama

        logger.info(f"Connecting to Ollama server at {OLLAMA_BASE_URL} with model '{OLLAMA_MODEL}'...")
        chat_model = ChatOllama(
            base_url=OLLAMA_BASE_URL,
            model=OLLAMA_MODEL,
            temperature=0.0,
            num_predict=512,
        )
        logger.info("[LangChain] ChatOllama initialized successfully.")
        return chat_model

    is_cuda = torch.cuda.is_available()
    device_str = "CUDA GPU" if is_cuda else "CPU"
    logger.info(f"Loading local HuggingFace LLM ({LLM_MODEL_NAME}) on {device_str}...")

    is_local = os.path.exists(LLM_MODEL_NAME)
    tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL_NAME, local_files_only=is_local)

    # PyTorch 4-bit Quantization & Memory Optimization
    quantization_config = None
    torch_dtype = torch.bfloat16 if is_cuda else torch.float32

    if is_cuda and USE_4BIT_QUANTIZATION:
        logger.info("[PyTorch] Enabling 4-bit (NF4) quantization...")
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )

    model_kwargs = {
        "torch_dtype": torch_dtype,
        "device_map": "auto" if is_cuda else None,
        "local_files_only": is_local,
    }
    if quantization_config:
        model_kwargs["quantization_config"] = quantization_config
    elif is_cuda:
        model_kwargs["attn_implementation"] = "sdpa"

    model = AutoModelForCausalLM.from_pretrained(LLM_MODEL_NAME, **model_kwargs)

    # HuggingFace Pipeline -> LangChain ChatModel conversion
    logger.info("[LangChain] Creating HuggingFace Pipeline...")
    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=512,
        do_sample=False,
        repetition_penalty=1.05,
        return_full_text=False,
    )
    hf_llm = HuggingFacePipeline(pipeline=pipe)
    chat_model = ChatHuggingFace(llm=hf_llm)
    logger.info("[LangChain] ChatHuggingFace model initialized successfully.")

    return chat_model
