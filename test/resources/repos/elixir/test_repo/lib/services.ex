defmodule TestRepo.Services do
  @moduledoc """
  Services module demonstrating function usage and dependencies.
  Similar to Python's services.py, this module uses the models defined in TestRepo.Models.
  """

  alias TestRepo.Models.{User, Item, Order, Serializable}

  defmodule UserService do
    use GenServer

    # Client API

    @doc """
    Starts the UserService GenServer.
    """
    def start_link(opts \\ []) do
      GenServer.start_link(__MODULE__, %{}, opts)
    end

    @doc """
    Creates a new user and stores it.
    """
    def create_user(pid, id, name, email, roles \\ []) do
      GenServer.call(pid, {:create_user, id, name, email, roles})
    end

    @doc """
    Gets a user by ID.
    """
    def get_user(pid, id) do
      GenServer.call(pid, {:get_user, id})
    end

    @doc """
    Lists all users.
    """
    def list_users(pid) do
      GenServer.call(pid, :list_users)
    end

    @doc """
    Deletes a user by ID.
    """
    def delete_user(pid, id) do
      GenServer.call(pid, {:delete_user, id})
    end

    # Server callbacks

    @impl true
    def init(_) do
      {:ok, %{}}
    end

    @impl true
    def handle_call({:create_user, id, name, email, roles}, _from, users) do
      if Map.has_key?(users, id) do
        {:reply, {:error, "User with ID #{id} already exists"}, users}
      else
        user = User.new(id, name, email, roles)
        new_users = Map.put(users, id, user)
        {:reply, {:ok, user}, new_users}
      end
    end

    @impl true
    def handle_call({:get_user, id}, _from, users) do
      case Map.get(users, id) do
        nil -> {:reply, {:error, :not_found}, users}
        user -> {:reply, {:ok, user}, users}
      end
    end

    @impl true
    def handle_call(:list_users, _from, users) do
      user_list = Map.values(users)
      {:reply, user_list, users}
    end

    @impl true
    def handle_call({:delete_user, id}, _from, users) do
      if Map.has_key?(users, id) do
        new_users = Map.delete(users, id)
        {:reply, :ok, new_users}
      else
        {:reply, {:error, :not_found}, users}
      end
    end
  end

  defmodule ItemService do
    use Agent

    @doc """
    Starts the ItemService Agent.
    """
    def start_link(opts \\ []) do
      Agent.start_link(fn -> %{} end, opts)
    end

    @doc """
    Creates a new item and stores it.
    """
    def create_item(pid, id, name, price, category) do
      Agent.get_and_update(pid, fn items ->
        if Map.has_key?(items, id) do
          {{:error, "Item with ID #{id} already exists"}, items}
        else
          item = Item.new(id, name, price, category)
          new_items = Map.put(items, id, item)
          {{:ok, item}, new_items}
        end
      end)
    end

    @doc """
    Gets an item by ID.
    """
    def get_item(pid, id) do
      Agent.get(pid, fn items ->
        case Map.get(items, id) do
          nil -> {:error, :not_found}
          item -> {:ok, item}
        end
      end)
    end

    @doc """
    Lists all items, optionally filtered by category.
    """
    def list_items(pid, category \\ nil) do
      Agent.get(pid, fn items ->
        item_list = Map.values(items)

        case category do
          nil -> item_list
          cat -> Enum.filter(item_list, &Item.in_category?(&1, cat))
        end
      end)
    end

    @doc """
    Deletes an item by ID.
    """
    def delete_item(pid, id) do
      Agent.get_and_update(pid, fn items ->
        if Map.has_key?(items, id) do
          new_items = Map.delete(items, id)
          {:ok, new_items}
        else
          {{:error, :not_found}, items}
        end
      end)
    end
  end

  defmodule OrderService do
    @doc """
    Creates a new order.
    """
    def create_order(id, user, items \\ []) do
      Order.new(id, user, items)
    end

    @doc """
    Adds an item to an existing order.
    """
    def add_item_to_order(order, item) do
      Order.add_item(order, item)
    end

    @doc """
    Updates the status of an order.
    """
    def update_order_status(order, status) do
      Order.update_status(order, status)
    end

    @doc """
    Processes an order (changes status to :processing).
    """
    def process_order(order) do
      update_order_status(order, :processing)
    end

    @doc """
    Completes an order (changes status to :completed).
    """
    def complete_order(order) do
      update_order_status(order, :completed)
    end

    @doc """
    Cancels an order (changes status to :cancelled).
    """
    def cancel_order(order) do
      update_order_status(order, :cancelled)
    end
  end

  @doc """
  Factory function to create a service container.
  """
  def create_service_container do
    {:ok, user_service} = UserService.start_link()
    {:ok, item_service} = ItemService.start_link()

    %{
      user_service: user_service,
      item_service: item_service,
      order_service: OrderService
    }
  end

  @doc """
  Helper function to serialize any model that implements the Serializable protocol.
  """
  def serialize_model(model) do
    Serializable.to_map(model)
  end

  # Module-level variables for testing
  @sample_user_id "sample_user"
  @sample_item_id "sample_item"

  @doc """
  Gets the sample user ID.
  """
  def sample_user_id, do: @sample_user_id

  @doc """
  Gets the sample item ID.
  """
  def sample_item_id, do: @sample_item_id

  # Create some sample data at module load time
  def setup_sample_data(container) do
    # Create sample user
    UserService.create_user(
      container.user_service,
      @sample_user_id,
      "Sample User",
      "sample@example.com",
      ["user", "customer"]
    )

    # Create sample item
    ItemService.create_item(
      container.item_service,
      @sample_item_id,
      "Sample Widget",
      29.99,
      "electronics"
    )
  end
end 