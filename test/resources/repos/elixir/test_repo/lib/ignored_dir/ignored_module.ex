defmodule TestRepo.IgnoredDir.IgnoredModule do
  @moduledoc """
  This module is in a directory that should be ignored by the language server.
  It's used for testing directory filtering functionality.
  """

  alias TestRepo.Models.User

  @doc """
  This function references the User model to test that ignored directories
  don't show up in symbol references.
  """
  def create_ignored_user do
    User.new("ignored", "Ignored User", "ignored@example.com")
  end

  @doc """
  Another function that uses models.
  """
  def process_ignored_user(user) do
    User.add_role(user, "ignored_role")
  end
end 