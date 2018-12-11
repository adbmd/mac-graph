
import tensorflow as tf

from .types import *
from .query import *

from ..util import *
from ..attention import *
from ..input import UNK_ID, get_table_with_embedding
from ..layers import *

read_control_parts = ["token_content", "token_index", "step_const", "memory", "prev_output"]


# TODO: Make indicator row data be special token

def read_from_table(args, features, in_signal, noun, table, width, keys_len=None):

	if args["read_indicator_cols"] > 0:
		ind_col = tf.get_variable(f"{noun}_indicator_col", [1, 1, args["read_indicator_cols"]])
		ind_col = tf.tile(ind_col, [features["d_batch_size"], tf.shape(table)[1], 1])
		table = tf.concat([table, ind_col], axis=2)
		width += args["read_indicator_cols"]

	query = tf.layers.dense(in_signal, width)

	output, total_raw_score, taps = attention(table, query,
		key_width=width, 
		keys_len=keys_len,
		name="read_from_"+noun,
	)

	output = dynamic_assert_shape(output, [features["d_batch_size"], width])
	return output, table, total_raw_score, taps


def read_from_table_with_embedding(args, features, vocab_embedding, in_signal, noun):
	"""Perform attention based read from table

	Will transform table into vocab embedding space
	
	@returns read_data
	"""

	with tf.name_scope(f"read_from_{noun}"):

		table, full_width, keys_len = get_table_with_embedding(args, features, vocab_embedding, noun)

		# --------------------------------------------------------------------------
		# Read
		# --------------------------------------------------------------------------

		return read_from_table(args, features, 
			in_signal, 
			noun,
			table, 
			width=full_width, 
			keys_len=keys_len)


def read_cell(context:CellContext, head_index:int,
	args:dict, features:dict, vocab_embedding, 
	in_memory_state, in_control_state, in_prev_outputs,
	in_question_tokens, in_question_state, 
	in_iter_id):
	"""
	A read cell

	@returns read_data

	"""

	attention_master_signal = tf.concat([context.in_iter_id, context.in_question_state], -1)


	with tf.name_scope("read_cell"):

		tap_attns = []
		tap_table = None
		taps = {}

		reads = []
		attn_focus = []

		# --------------------------------------------------------------------------
		# Read data from nodes and edges
		# --------------------------------------------------------------------------

		for i in args["kb_list"]:

			read_query, rcq_taps = generate_query(context, i + str(head_index))

			read, table, score_raw_total, read_table_taps = read_from_table_with_embedding(
				args, 
				features, 
				vocab_embedding, 
				read_query, 
				noun=i
			)

			for k,v in {**read_table_taps, **rcq_taps}.items():
				taps[i + str(head_index) + "_" + k] = v

			attn_focus.append(score_raw_total)

			read_words = tf.reshape(read, [features["d_batch_size"], args[i+"_width"], args["embed_width"]])	
		
			d, taps[i + str(head_index) + "_word_attn"] = attention_by_index(read_words, attention_master_signal, name=i+"_word_attn")
			d = tf.concat([d, attention_master_signal], -1)
			d = layer_dense(d, args["read_width"], args["read_activation"])
			reads.append(d)

		if len(reads) > 0:
			read_width = reads[0].shape[-1] # Some activations are naughty and make the output wider than asked for
		else:
			read_width = args["read_width"]

		# --------------------------------------------------------------------------
		# Read data from previous outputs of the network
		# --------------------------------------------------------------------------


		if args["use_read_previous_outputs"]:
			# Address by content

			in_prev_outputs_padded = tf.pad(in_prev_outputs, [[0,0],[0, args["max_decode_iterations"] - tf.shape(in_prev_outputs)[1]],[0,0]])
			in_prev_outputs_padded.set_shape([None, args["max_decode_iterations"], None])
			
			prev_output_query = tf.layers.dense(attention_master_signal, args["output_width"])
			prev_output_content_signal, _, x_taps = attention(in_prev_outputs_padded, prev_output_query)
			reads.append(tf.layers.dense(prev_output_content_signal, read_width))
			taps[f"read{head_index}_po_content_attn"] = x_taps["attn"]

			# Address by index

			prev_output_index_signal, query = attention_by_index(in_prev_outputs_padded, attention_master_signal)
			reads.append(tf.layers.dense(prev_output_index_signal, read_width))
			taps[f"read{head_index}_po_index_attn"] = query


		# --------------------------------------------------------------------------
		# Select between read sources
		# --------------------------------------------------------------------------

		reads = tf.stack(reads, axis=1)
		read_word, taps[f"read{head_index}_head_attn"] = attention_by_index(reads, attention_master_signal, name=f"read{head_index}_head_attn")

		# --------------------------------------------------------------------------
		# Prepare and shape results
		# --------------------------------------------------------------------------
		
		# Residual skip connection
		out_data = tf.concat([read_word, attention_master_signal] + attn_focus, -1)
		out_data = tf.layers.dense(out_data, args["read_width"]) # shape for residual
		
		for i in range(args["read_layers"]):
			prev_layer = out_data
			out_data = layer_dense(out_data, args["read_width"], args["read_activation"], dropout=args["read_dropout"])
			if out_data.shape[-1] == prev_layer.shape[-1]:
				out_data += prev_layer

		if len(attn_focus) > 0:
			taps[f"read{head_index}_head_attn_focus"] = tf.concat(attn_focus, -1)
		else:
			taps[f"read{head_index}_head_attn_focus"] = tf.zeros([features["d_batch_size"],1])

		return out_data, taps




