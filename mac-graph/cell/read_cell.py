
import tensorflow as tf

from ..util import *
from ..attention import *
from ..input import UNK_ID
from ..minception import *

# TODO: Make indicator row data be special token

def read_from_table(args, features, in_signal, noun, table, width, table_len, table_max_len, use_mask=False):

	if args["read_indicator_cols"] > 0:
		ind_col = tf.get_variable(f"{noun}_indicator_col", [1, 1, args["read_indicator_cols"]])
		ind_col = tf.tile(ind_col, [features["d_batch_size"], tf.shape(table)[1], 1])
		table = tf.concat([table, ind_col], axis=2)
		width += args["read_indicator_cols"]

	# query = tf.layers.dense(in_signal, width, activation=tf.nn.tanh)
	query = tf.layers.dense(in_signal, width)

	if use_mask:
		mask  = tf.layers.dense(in_signal, width, activation=tf.nn.tanh)
	else:
		mask = None


	output, score = attention(table, query, mask, 
		word_size=width, 
		table_len=table_len,
		table_max_len=table_max_len,
	)

	output = dynamic_assert_shape(output, [features["d_batch_size"], width])
	return output, score, table


def read_from_table_with_embedding(args, features, vocab_embedding, in_signal, noun):
	"""Perform attention based read from table

	Will transform table into vocab embedding space
	
	@returns read_data
	"""

	with tf.name_scope(f"read_from_{noun}"):

		# --------------------------------------------------------------------------
		# Constants and validations
		# --------------------------------------------------------------------------

		table = features[f"{noun}s"]
		table_len = features[f"{noun}s_len"]

		width = args[f"{noun}_width"]
		full_width = width * args["embed_width"]

		d_len = tf.shape(table)[1]
		assert table.shape[-1] == width


		# --------------------------------------------------------------------------
		# Extend table if desired
		# --------------------------------------------------------------------------

		if args["read_indicator_rows"] > 0:
			# Add a trainable row to the table
			ind_row_shape = [features["d_batch_size"], args["read_indicator_rows"], width]
			ind_row = tf.fill(ind_row_shape, tf.cast(UNK_ID, table.dtype))
			table = tf.concat([table, ind_row], axis=1)
			table_len += args["read_indicator_rows"]
			d_len += args["read_indicator_rows"]

		# --------------------------------------------------------------------------
		# Embed graph tokens
		# --------------------------------------------------------------------------
		
		emb_kb = tf.nn.embedding_lookup(vocab_embedding, table)
		emb_kb = dynamic_assert_shape(emb_kb, 
			[features["d_batch_size"], d_len, width, args["embed_width"]])

		emb_kb = tf.reshape(emb_kb, [-1, d_len, full_width])
		emb_kb = dynamic_assert_shape(emb_kb, 
			[features["d_batch_size"], d_len, full_width])

		# --------------------------------------------------------------------------
		# Read
		# --------------------------------------------------------------------------

		return read_from_table(args, features, 
			in_signal, 
			noun,
			emb_kb, 
			width=full_width, 
			table_len=table_len, 
			table_max_len=args[f"{noun}_max_len"])



def read_cell(args, features, vocab_embedding, in_memory_state, in_control_state, in_data_stack, in_question_tokens):
	"""
	A read cell

	@returns read_data

	"""


	with tf.name_scope("read_cell"):

		# --------------------------------------------------------------------------
		# Read data
		# --------------------------------------------------------------------------

		in_signal = []

		if in_memory_state is not None and args["use_memory_cell"]:
			in_signal.append(in_memory_state)

		# We may run the network with no control cell
		if in_control_state is not None and args["use_control_cell"]:
			in_signal.append(in_control_state)

		# hack to take questions in
		# are <space> number <space> and <space> number ...
		# src  = tf.nn.embedding_lookup(vocab_embedding, features["src"])
		# src = dynamic_assert_shape(src, [batch_size, seq_len, args["embed_width"]])

		in_signal = [in_question_tokens[:,2], in_question_tokens[:,6]]

		in_signal = tf.concat(in_signal, -1)

		reads = []
		tap_attns = []
		tap_table = None

		for i in ["kb_node", "kb_edge"]:
			if args[f"use_{i}"]:
				for j in range(args["read_heads"]):
					read, attn, table = read_from_table_with_embedding(
						args, 
						features, 
						vocab_embedding, 
						in_signal, 
						noun=i
					)
					reads.append(read)
					tap_attns.append(attn)
					tap_table = table

		if args["use_data_stack"]:
			# Attentional read
			read, attn, table = read_from_table(args, features, in_signal, noun, in_data_stack, args["data_stack_width"])
			reads.append(read)
			# Head read
			reads.append(in_data_stack[:,0,:])

		read_data = tf.concat(reads, -1)
		tap_attns = tf.concat(tap_attns, axis=-1)


		# --------------------------------------------------------------------------
		# Prepare and shape results
		# --------------------------------------------------------------------------
		
		# in theory compare if the output and signal are similar

		# final_signal = tf.concat([in_signal, read_data], -1)
		# final_signal = read_data

		delta = read_data - tf.layers.dense(in_signal, read_data.shape[-1])
		t_abs = tf.nn.relu(delta) + tf.nn.relu(-delta)
		out_data = tf.nn.dropout(t_abs, 1.0-args["read_dropout"])
		# score = tf.layers.dense(t_abs, args["answer_classes"])
		# score, tap_act = mi_activation(score)


		# old style

		# out_data = tf.layers.dense(read_data, args["memory_width"], name="data_read_shrink")
		# out_data = dynamic_assert_shape(out_data, [features["d_batch_size"], args["memory_width"]])
		# out_data, tap_act = mi_activation(out_data, tap=True)
		# out_data = tf.nn.dropout(out_data, 1.0-args["read_dropout"])
		# out_data = dynamic_assert_shape(out_data, [features["d_batch_size"], args["memory_width"]])

		return out_data, tap_attns, tap_table




